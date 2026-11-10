"""Resource-bounded Docker execution; candidates never see the daemon socket."""
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import uuid

DEFAULT_IMAGE = 'rigmark-quality-runtime:0.4'


class EventCollector:
    def __init__(self):
        self.events = {'go_pass': set(), 'python_pass': set(), 'python_failed': set(),
                       'unittest_ran': None, 'unittest_ok': False,
                       'source_error': False, 'build_failed': False,
                       'c_compile_error': False}
        self.pending = b''

    def visit(self, raw):
        if len(raw) > 8192:
            return
        line = raw.decode('utf-8', errors='replace').strip()
        events = self.events
        if match := re.match(r'^--- PASS: (\S+) \(', line):
            events['go_pass'].add(match.group(1))
        if match := re.match(r'^\S+ \(([^)]+)\) \.\.\. ok$', line):
            events['python_pass'].add(match.group(1))
        if match := re.match(r'^(?:FAIL|ERROR): \S+ \(([^)]+)\)(?: \(.*\))?$', line):
            events['python_failed'].add(match.group(1))
        if match := re.match(r'^Ran (\d+) tests? in ', line):
            events['unittest_ran'] = int(match.group(1))
            events['unittest_ok'] = False
        if line == 'OK' and events['unittest_ran'] is not None:
            events['unittest_ok'] = True
        events['source_error'] |= any(word in line for word in
                                      ('SyntaxError', 'ImportError', 'ModuleNotFoundError'))
        events['build_failed'] |= '[build failed]' in line.lower()
        events['c_compile_error'] |= bool(re.search(r':\d+:\d+: error:|undefined reference',
                                                    line.lower()))

    def feed(self, chunk):
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()[-8192:]
        for line in lines:
            self.visit(line)

    def finish(self):
        if self.pending:
            self.visit(self.pending)
        return {key: sorted(value) if isinstance(value, set) else value
                for key, value in self.events.items()}


def terminal_events(log):
    """Extract grading events from a bounded, already completed log."""
    log.seek(0)
    collector = EventCollector()
    while chunk := log.read(65536):
        collector.feed(chunk)
    return collector.finish()


def capture(command, timeout=60, max_output_bytes=4 * 1024 * 1024):
    """Bound wall time, output bytes, and retained output during execution."""
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True, bufsize=0)
    collector = EventCollector()
    head, tail = bytearray(), bytearray()
    size = 0
    timed_out = False
    output_limited = False
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(p.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            if not selector.select(remaining):
                timed_out = True
                break
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                selector.unregister(p.stdout)
                break
            size += len(chunk)
            if size > max_output_bytes:
                output_limited = True
                break
            collector.feed(chunk)
            if len(head) < 32768:
                head.extend(chunk[:32768 - len(head)])
            tail.extend(chunk)
            if len(tail) > 32768:
                del tail[:-32768]
    if timed_out or output_limited:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    p.wait()
    p.stdout.close()
    output = (bytes(head).decode('utf-8', errors='replace')
              if size <= 32768 else
              bytes(head).decode('utf-8', errors='replace') +
              '\n[intermediate output omitted]\n' +
              bytes(tail).decode('utf-8', errors='replace'))
    if output_limited:
        output += '\n[output limit exceeded]\n'
    return {'exit_code': -1 if output_limited else p.returncode,
            'timeout': timed_out,
            'output_limited': output_limited, 'output': output,
            'terminal_events': collector.finish()}


def image_id(image):
    return subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()


def run(workspace, image, command, timeout=120):
    name = 'rigmark-quality-' + uuid.uuid4().hex[:12]
    args = ['docker', 'run', '--name', name, '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=128',
            '--memory=2g', '--cpus=2', f'--user={os.getuid()}:{os.getgid()}',
            '--tmpfs=/tmp:rw,exec,nosuid,nodev,size=768m,mode=1777',
            '-e', 'HOME=/tmp', '-e', 'GOCACHE=/tmp/go-cache', '-e', 'GOPROXY=off',
            '-e', 'GOTOOLCHAIN=local', '-e', 'GOSUMDB=off',
            '-v', f'{workspace.resolve()}:/workspace:rw', '-w', '/workspace', image,
            '/bin/sh', '-c', command]
    try:
        return capture(args, timeout)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)


def public_command(task_id):
    return {
        'python-expiry': 'python3 -B -m unittest -v test_expiry',
        'node-idempotency': 'node store.test.js',
        'go-worker-pool': 'go test -race -count=1 -timeout=60s ./...',
        'go-transfer-ledger': 'go test -race -count=1 -timeout=60s ./...',
        'statement-redact': 'python3 -B test_statement.py',
        'sqlite-migration': 'python3 -B -m unittest -v test_migration',
        'sqlite-report': 'python3 -B -m unittest -v test_report',
        'go-shutdown-deadlock': 'go test -race -count=1 -timeout=60s ./...',
        'go-export-boundary': 'go test -race -count=1 -timeout=60s ./...',
        'c-frame-bounds': 'cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -no-pie frame.c frame_test.c -o /tmp/rigmark-frame && ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 /tmp/rigmark-frame',
    }[task_id]


def acceptance_command(task_id):
    return {
        'python-expiry': 'python3 -B rigmark_acceptance.py',
        'node-idempotency': 'node rigmark_acceptance.js',
        'go-worker-pool': 'go test -race -count=1 -timeout=60s ./... -run "TestRigmarkAcceptance"',
        'go-transfer-ledger': 'go test -race -count=1 -timeout=60s ./... -run "TestRigmarkAcceptance"',
        'arkade-add': 'go test -mod=vendor -count=1 -timeout=60s ./pkg/get -run "TestRigmarkAcceptance"',
        'sqlite-migration': 'python3 -B -m unittest -v sqlite_migration_acceptance',
        'sqlite-report': 'python3 -B -m unittest -v sqlite_report_acceptance',
        'go-shutdown-deadlock': 'go test -json -race -count=1 -timeout=60s -run "^TestRigmarkAcceptanceShutdown$" .',
        'go-export-boundary': 'go test -json -race -count=1 -timeout=60s -run "^TestRigmarkAcceptanceTenantBoundary$" .',
        'c-frame-bounds': 'cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -no-pie frame.c rigmark_acceptance.c -o /tmp/rigmark-frame && ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 /tmp/rigmark-frame',
    }[task_id]
