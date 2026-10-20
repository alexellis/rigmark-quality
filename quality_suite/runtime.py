"""Resource-bounded Docker execution; candidates never see the daemon socket."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import uuid

DEFAULT_IMAGE = 'rigmark-quality-runtime:0.4'


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
        log.seek(0)
        output = log.read(65536).decode('utf-8', errors='replace')
        return {'exit_code': p.returncode, 'timeout': timed_out, 'output': output}


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


def require_judge_started(result):
    """Docker's reserved exit codes mean the judge did not execute."""
    output = result.get('output', '')
    if (result['exit_code'] == 125 or
            (result['exit_code'] in (126, 127) and
             ('docker:' in output.lower() or 'error response from daemon' in output.lower()))):
        raise RuntimeError('judge container failed to start: '
                           + output[-500:])


def public_command(task_id):
    return {
        'python-expiry': 'python3 -B -m unittest -v test_expiry',
        'node-idempotency': 'node store.test.js',
        'go-worker-pool': 'go test -race -count=1 -timeout=60s ./...',
        'go-transfer-ledger': 'go test -race -count=1 -timeout=60s ./...',
        'statement-redact': 'python3 -B test_statement.py',
    }[task_id]


def acceptance_command(task_id):
    return {
        'python-expiry': 'python3 -B rigmark_acceptance.py',
        'node-idempotency': 'node rigmark_acceptance.js',
        'go-worker-pool': 'go test -race -count=1 -timeout=60s ./... -run "TestRigmarkAcceptance"',
        'go-transfer-ledger': 'go test -race -count=1 -timeout=60s ./... -run "TestRigmarkAcceptance"',
        'arkade-add': 'go test -mod=vendor -count=1 -timeout=60s ./pkg/get -run "TestRigmarkAcceptance"',
    }[task_id]
