"""Resource-bounded Docker execution; candidates never see the daemon socket."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import uuid

DEFAULT_IMAGE = 'rigmark-quality-runtime:0.4'


def terminal_events(log):
    """Retain grading events from the entire log without retaining the log."""
    log.seek(0)
    events = {'go_pass': set(), 'python_pass': set(), 'python_failed': set(),
              'unittest_ran': None, 'unittest_ok': False,
              'source_error': False, 'build_failed': False,
              'c_compile_error': False}
    pending = b''

    def visit(raw):
        if len(raw) > 8192:
            return
        line = raw.decode('utf-8', errors='replace').strip()
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

    while chunk := log.read(65536):
        lines = (pending + chunk).split(b'\n')
        pending = lines.pop()[-8192:]
        for line in lines:
            visit(line)
    if pending:
        visit(pending)
    return {key: sorted(value) if isinstance(value, set) else value
            for key, value in events.items()}


def capture(command, timeout=60):
    # A file avoids unbounded RAM use if candidate code prints continuously.
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        evidence = terminal_events(log)
        size = log.seek(0, os.SEEK_END)
        if size <= 65536:
            log.seek(0)
            output = log.read().decode('utf-8', errors='replace')
        else:
            log.seek(0)
            head = log.read(32768).decode('utf-8', errors='replace')
            log.seek(size - 32768)
            tail = log.read().decode('utf-8', errors='replace')
            output = head + '\n[intermediate output omitted]\n' + tail
        return {'exit_code': p.returncode, 'timeout': timed_out,
                'output': output, 'terminal_events': evidence}


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
