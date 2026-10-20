"""Run arkade-add as an ordinary OpenCode session in Docker or Slicer."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid

from . import evaluators, runtime, tasks


PROMPT = tasks.TASKS['arkade-add']['prompt']
DEFAULT_AGENT_IMAGE = 'rigmark-quality-agent:0.8'


class TransportError(RuntimeError):
    """The provider failed before the agent could complete its task."""


def command(argv, *, timeout=300, output=None):
    """Run one host command without a shell, retaining diagnostics on failure."""
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if output:
        with Path(output).open('a') as stream:
            stream.write('$ ' + ' '.join(argv[:4]) + '\n' + result.stdout + '\n')
    if result.returncode:
        raise RuntimeError(f'{" ".join(argv[:4])} exited {result.returncode}: '
                           f'{result.stdout[-3000:]}')
    return result.stdout


def original_is_pinned(root):
    path = Path(root) / 'pkg/get/tools.go'
    if not path.is_file():
        raise ValueError(f'arkade source missing: {path}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != tasks.ARKADE_TOOLS_SHA256:
        raise ValueError(f'arkade source is not pinned at {tasks.ARKADE_REVISION}')


def changed_go_files(candidate, original):
    result = []
    source = Path(original) / 'pkg/get'
    for path in sorted((Path(candidate) / 'pkg/get').glob('*.go')):
        prior = source / path.name
        if not prior.exists() or prior.read_bytes() != path.read_bytes():
            result.append('pkg/get/' + path.name)
    return result


def grade(candidate, original, image):
    """Judge final files without prescribing the agent's test filename."""
    linked = [str(path.relative_to(candidate)) for path in Path(candidate).rglob('*')
              if path.is_symlink()]
    if linked:
        return {'candidate_has_no_symlinks': False}, {'symlink_paths': linked}
    changed = changed_go_files(candidate, original)
    test_files = [path for path in changed if path.endswith('_test.go')]
    public = runtime.run(candidate, image,
                         'go test -mod=vendor -count=1 -timeout=90s ./pkg/get', 180)
    runtime.require_judge_started(public)
    formatted = runtime.run(candidate, image,
                            'gofmt -l ' + ' '.join(map(shlex.quote, changed))
                            if changed else 'true', 30)
    runtime.require_judge_started(formatted)
    with tempfile.TemporaryDirectory(prefix='rigmark-arkade-judge-') as directory:
        judged = Path(directory) / 'candidate'
        shutil.copytree(candidate, judged)
        for name, content in evaluators.files('arkade-add', Path(original)).items():
            target = judged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        acceptance = runtime.run(judged, image,
                                 runtime.acceptance_command('arkade-add'), 180)
        runtime.require_judge_started(acceptance)
    readme = (Path(candidate) / 'README.md').read_text()
    checks = {
        'public_tests': public['exit_code'] == 0 and not public['timeout'],
        'independent_urls': acceptance['exit_code'] == 0 and not acceptance['timeout'],
        'readme': ('| [shfmt](https://github.com/mvdan/sh)' in readme
                   and 'There are 221 tools' in readme),
        'agent_test': bool(test_files) and any(
            re.search(r'func\s+Test\w*Shfmt\b',
                      (Path(candidate) / path).read_text(), re.IGNORECASE)
            for path in test_files),
        'gofmt': formatted['exit_code'] == 0 and not formatted['output'].strip(),
    }
    return checks, {'public_tests': public, 'acceptance': acceptance,
                    'format': formatted, 'changed_go_files': changed}


def _model_events(path):
    observed = set()
    data = Path(path).read_text(errors='replace')
    try:
        events = [json.loads(data)]
    except ValueError:
        events = []
        for line in data.splitlines():
            try:
                events.append(json.loads(line[line.index('{'):]))
            except ValueError:
                pass
    for event in events:
        stack = [event]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                provider = value.get('providerID')
                model = value.get('modelID')
                if isinstance(provider, str) and isinstance(model, str):
                    observed.add(provider + '/' + model)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    if not observed and not events:
        # OpenCode can emit an incomplete export while still exiting zero.
        # Its session header and completed message headers precede the cut.
        pairs = re.findall(r'"providerID"\s*:\s*"([^"\\]+)"\s*,\s*'
                           r'"modelID"\s*:\s*"([^"\\]+)"', data)
        observed.update(f'{provider}/{model}' for provider, model in pairs)
        header = re.search(r'"model"\s*:\s*\{\s*"id"\s*:\s*"([^"\\]+)"'
                           r'\s*,\s*"providerID"\s*:\s*"([^"\\]+)"', data)
        if header:
            observed.add(header.group(2) + '/' + header.group(1))
    return sorted(observed)


def _session_id(path):
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            event = json.loads(line[line.index('{'):])
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get('sessionID'), str):
            return event['sessionID']
    return None


def _agent_error(path):
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            event = json.loads(line[line.index('{'):])
        except ValueError:
            continue
        if event.get('type') == 'error':
            detail = event.get('error', {}).get('data', {}).get('message')
            return detail if isinstance(detail, str) else 'provider error'
    return None


def _instruction_evidence(path):
    """Record observable AGENTS.md steps without requiring one tool spelling."""
    release_lookup = False
    download_verified = False
    publish_attempt = False
    for line in Path(path).read_text(errors='replace').splitlines():
        try:
            event = json.loads(line[line.index('{'):])
        except ValueError:
            continue
        if event.get('type') != 'tool_use':
            continue
        state = event.get('part', {}).get('state', {})
        if state.get('status') != 'completed':
            continue
        command_text = state.get('input', {}).get('command', '')
        if not isinstance(command_text, str):
            continue
        if ('github.com/mvdan/sh/releases' in command_text
                or 'gh release view' in command_text):
            release_lookup = True
        if re.search(r'\b(?:git\s+commit|gh\s+pr\s+create)\b', command_text):
            publish_attempt = True
        if (re.search(r'(?:^|[ /])(?:hack/)?test-tool\.sh\s+shfmt\b', command_text)
                and state.get('metadata', {}).get('exit') == 0):
            download_verified = True
    return {'release_lookup_seen': release_lookup,
            'platform_download_script_passed': download_verified,
            'publish_attempt_seen': publish_attempt}


def _pinned_config(agent_model, source):
    """Give the build agent and its small helper the same contender."""
    config = json.loads(Path(source).expanduser().read_text())
    config['model'] = agent_model
    config['small_model'] = agent_model
    handle, name = tempfile.mkstemp(prefix='rigmark-opencode-', suffix='.json')
    os.chmod(name, 0o600)
    with os.fdopen(handle, 'w') as stream:
        json.dump(config, stream)
    return Path(name)


def _portable_config(agent_model, source, destination):
    """Copy only the selected provider, omitting host-wide OpenCode settings."""
    source = Path(source).expanduser()
    source_config = json.loads(source.read_text()) if source.is_file() else {}
    provider = agent_model.split('/', 1)[0]
    config = {'model': agent_model, 'small_model': agent_model}
    if provider in source_config.get('provider', {}):
        config['provider'] = {provider: source_config['provider'][provider]}
    destination.write_text(json.dumps(config))
    destination.chmod(0o600)


def _portable_auth(agent_model, source, destination):
    """Copy only the selected provider's OpenCode auth entry, if present."""
    source = Path(source).expanduser()
    if not source.is_file():
        return False
    provider = agent_model.split('/', 1)[0]
    auth = json.loads(source.read_text())
    if provider not in auth:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({provider: auth[provider]}))
    destination.chmod(0o600)
    return True


def _wait(vm, exec_id, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        remaining = max(1, min(30, int(deadline - time.monotonic())))
        result = subprocess.run(['slicer', 'vm', 'bg', 'wait', vm, exec_id,
                                 '--timeout', f'{remaining}s', '--json'],
                                text=True, capture_output=True, timeout=remaining + 15)
        if result.returncode == 0:
            return json.loads(result.stdout)
        if 'timed out' not in (result.stdout + result.stderr).lower():
            raise RuntimeError('Slicer wait failed: ' + (result.stdout + result.stderr)[-2000:])
    command(['slicer', 'vm', 'bg', 'kill', vm, exec_id], timeout=30)
    return {'exit_code': None, 'timeout': True}


def run_slicer(model, agent_model, original, image, output, seconds=1800,
        keep_vm=False, config_file=None, variant=None):
    """Provision, clone, run, collect, and judge one fresh native-agent attempt."""
    original_is_pinned(original)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    vm = 'rigmark-arkade-' + run_id
    tag = 'run=rigmark-arkade-' + run_id
    log = output / f'{run_id}-agent.jsonl'
    session_export = output / f'{run_id}-session.json'
    setup_log = output / f'{run_id}-setup.log'
    start = datetime.now(timezone.utc).isoformat()
    began = time.monotonic()
    created = False
    pinned_config = None
    agent_exit = None
    checks = {}
    details = {}
    process_checks = {}
    failure = None
    failure_category = None
    setup_seconds = agent_seconds = judge_seconds = None
    observed = []
    instruction_evidence = {}
    try:
        source_config = config_file or Path.home() / '.config/opencode/opencode.json'
        pinned_config = _pinned_config(agent_model, source_config)
        launch = ['slicer', 'opencode', '--name', vm,
                  '--tag', 'workflow=rigmark-quality-arkade', '--tag', tag,
                  '--cpus', '2', '--ram-gb', '4', '--rm',
                  '--config-file', str(pinned_config)]
        created = True  # A partial launch may still need cleanup.
        command(launch, timeout=360, output=setup_log)
        command(['slicer', 'vm', 'exec', vm, '--shell', '', '--', 'git',
                 'clone', 'https://github.com/alexellis/arkade.git',
                 '/home/ubuntu/arkade'], timeout=180, output=setup_log)
        command(['slicer', 'vm', 'exec', vm, '--shell', '', '--', 'git',
                 '-C', '/home/ubuntu/arkade', 'checkout', '--detach',
                 tasks.ARKADE_REVISION], timeout=60, output=setup_log)
        command(['slicer', 'vm', 'exec', vm, '--',
                 'sudo arkade system install go'], timeout=360, output=setup_log)
        command(['slicer', 'vm', 'exec', vm, '--shell', '', '--', 'git',
                 '-C', '/home/ubuntu/arkade', 'rev-parse', 'HEAD'],
                timeout=30, output=setup_log)
        setup_seconds = round(time.monotonic() - began, 1)

        agent_started = time.monotonic()
        agent_command = ['slicer', 'vm', 'bg', 'exec', vm, '--cwd',
                         '/home/ubuntu/arkade', '--ring-bytes', '16M',
                         '--cmd', '/home/ubuntu/.arkade/bin/opencode',
                         '--arg', 'run', '--arg', '--auto',
                         '--arg', '--format', '--arg', 'json', '--arg', '--model',
                         '--arg', agent_model]
        if variant:
            agent_command += ['--arg', '--variant', '--arg', variant]
        agent_command += ['--arg', PROMPT, '--json']
        launched = command(agent_command,
                           timeout=60, output=setup_log)
        exec_id = json.loads(launched)['exec_id']
        result = _wait(vm, exec_id, seconds)
        agent_exit = result.get('exit_code')
        agent_seconds = round(time.monotonic() - agent_started, 1)
        with log.open('w') as stream:
            log_result = subprocess.run(['slicer', 'vm', 'bg', 'logs', vm, exec_id],
                                        stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=60)
        if log_result.returncode:
            provider_error = _agent_error(log)
            if provider_error:
                raise TransportError(provider_error)
            raise RuntimeError(f'could not collect agent log: {log.read_text()[-2000:]}')
        instruction_evidence = _instruction_evidence(log)
        process_checks['no_publish_attempt'] = not instruction_evidence['publish_attempt_seen']
        session_id = _session_id(log)
        if session_id:
            guest_export = '/home/ubuntu/rigmark-agent-session.json'
            command(['slicer', 'vm', 'exec', vm, '--cwd', '/home/ubuntu/arkade',
                     '--', '/home/ubuntu/.arkade/bin/opencode export '
                     + shlex.quote(session_id) + ' > ' + guest_export],
                    timeout=90, output=setup_log)
            command(['slicer', 'vm', 'cp', f'{vm}:{guest_export}',
                     str(session_export)], timeout=90, output=setup_log)
        observed = _model_events(session_export if session_export.exists() else log)
        if result.get('timeout'):
            failure = 'time_budget'
            failure_category = 'budget'
        elif agent_exit != 0:
            failure = f'agent_exit_{agent_exit}'
            failure_category = 'infrastructure'

        head = command(['slicer', 'vm', 'exec', vm, '--shell', '', '--',
                        'git', '-C', '/home/ubuntu/arkade', 'rev-parse', 'HEAD'],
                       timeout=30, output=setup_log).strip()
        process_checks['pinned_base'] = head == tasks.ARKADE_REVISION
        diff = subprocess.run(['slicer', 'vm', 'exec', vm, '--shell', '', '--',
                               'git', '-C', '/home/ubuntu/arkade', 'diff', '--check'],
                              text=True, capture_output=True, timeout=30)
        process_checks['diff_clean'] = diff.returncode == 0
        if diff.stdout or diff.stderr:
            with setup_log.open('a') as stream:
                stream.write('git diff --check\n' + diff.stdout + diff.stderr)

        judged_at = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='rigmark-arkade-native-') as directory:
            candidate = Path(directory) / 'arkade'
            command(['slicer', 'vm', 'cp', '-r',
                     '--exclude', '.git', '--exclude', '.git/**',
                     f'{vm}:/home/ubuntu/arkade', str(candidate)],
                    timeout=180, output=setup_log)
            checks, details = grade(candidate, original, image)
            process_checks['agents_file_present'] = (candidate / 'AGENTS.md').is_file()
            checks.update(process_checks)
        judge_seconds = round(time.monotonic() - judged_at, 1)
    except TransportError as exc:
        failure = f'transport_error: {exc}'
        failure_category = 'infrastructure'
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        failure = failure or f'harness_error: {exc}'
        failure_category = 'infrastructure'
    finally:
        if pinned_config:
            pinned_config.unlink(missing_ok=True)
        if created and not keep_vm:
            subprocess.run(['slicer', 'vm', 'delete', vm],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60)

    model_match = bool(observed) and observed == [agent_model]
    if failure is None and not model_match:
        failure = 'model_mismatch' if observed else 'model_unverified'
        failure_category = 'infrastructure'
    artefact_passed = bool(checks) and all(checks.values()) and model_match
    finished = agent_exit == 0
    return {
        'task': 'arkade-add', 'category': 'coding',
        'interpretation': 'diagnostic_only', 'task_status': 'experimental',
        'harness': 'slicer-opencode-native', 'suite_version': '0.8',
        'requested_model': model, 'agent_model': agent_model,
        'observed_models': observed, 'model_match': model_match,
        'arkade_revision': tasks.ARKADE_REVISION, 'prompt': PROMPT,
        'agent_variant': variant,
        'started_at': start, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': agent_seconds or 0, 'setup_seconds': setup_seconds,
        'judge_seconds': judge_seconds,
        'vm_tags': ['workflow=rigmark-quality-arkade', tag],
        'vm_retained': keep_vm and created, 'transcript': str(log) if log.exists() else None,
        'session_export': str(session_export) if session_export.exists() else None,
        'setup_log': str(setup_log), 'agent_exit_code': agent_exit,
        'instruction_evidence': instruction_evidence,
        'checks': checks, 'acceptance': details,
        'artefact_passed': artefact_passed,
        'conversation_finished': finished,
        'passed': artefact_passed and finished and failure is None,
        'failure': failure, 'failure_category': failure_category,
    }


def run_docker(model, agent_model, original, image, agent_image, output,
               seconds=1800, config_file=None, auth_file=None,
               api_key_env=None, variant=None):
    """Run the native agent in a disposable Docker container, then judge it."""
    original_is_pinned(original)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    name = 'rigmark-arkade-' + run_id
    log = output / f'{run_id}-agent.jsonl'
    session_export = output / f'{run_id}-session.json'
    setup_log = output / f'{run_id}-setup.log'
    start = datetime.now(timezone.utc).isoformat()
    began = time.monotonic()
    agent_exit = None
    checks = {}
    details = {}
    process_checks = {}
    failure = None
    failure_category = None
    setup_seconds = agent_seconds = judge_seconds = None
    observed = []
    instruction_evidence = {}
    container_id = None
    agent_image_id = None
    export_complete = None
    with tempfile.TemporaryDirectory(prefix='rigmark-arkade-docker-') as directory:
        root = Path(directory)
        candidate = root / 'arkade'
        home = root / 'home'
        try:
            agent_image_id = runtime.image_id(agent_image)
            shutil.copytree(original, candidate, symlinks=True)
            home.mkdir()
            config_dir = home / '.config/opencode'
            config_dir.mkdir(parents=True)
            config = config_dir / 'opencode.json'
            source_config = config_file or Path.home() / '.config/opencode/opencode.json'
            _portable_config(agent_model, source_config, config)
            if agent_model.startswith('toilgate/'):
                plugin = Path(source_config).expanduser().parent / 'plugins/toilgate.ts'
                if not plugin.is_file():
                    raise ValueError(f'Toilgate OpenCode plugin is missing: {plugin}')
                plugin_dir = config_dir / 'plugins'
                plugin_dir.mkdir()
                shutil.copy2(plugin, plugin_dir / 'toilgate.ts')
            selected_auth = (auth_file if auth_file and str(auth_file) != 'none'
                             else Path.home() / '.local/share/opencode/auth.json')
            _portable_auth(agent_model, selected_auth,
                           home / '.local/share/opencode/auth.json')
            if api_key_env and not os.environ.get(api_key_env):
                raise ValueError(f'{api_key_env} is not set')
            process_checks['agents_file_present'] = (candidate / 'AGENTS.md').is_file()
            process_checks['pinned_base'] = (command(
                ['git', '-C', str(candidate), 'rev-parse', 'HEAD'], timeout=30,
                output=setup_log).strip() == tasks.ARKADE_REVISION)
            setup_seconds = round(time.monotonic() - began, 1)

            argv = ['docker', 'run', '--detach', '--name', name,
                    '--network', 'bridge', '--add-host',
                    'host.docker.internal:host-gateway',
                    '--user', f'{os.getuid()}:{os.getgid()}',
                    '--read-only', '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--pids-limit', '256', '--cpus', '2', '--memory', '4g',
                    '-v', f'{candidate.resolve()}:/workspace:rw',
                    '-v', f'{home.resolve()}:/home/agent:rw',
                    '-e', 'HOME=/home/agent',
                    '-e', 'OPENCODE_CONFIG=/home/agent/.config/opencode/opencode.json',
                    '-e', 'OPENCODE_CONFIG_DIR=/home/agent/.config/opencode',
                    '-e', 'OPENCODE_DISABLE_AUTOUPDATE=true',
                    '-e', 'OPENCODE_AUTO_SHARE=false']
            if api_key_env:
                argv += ['-e', api_key_env]
            argv += [agent_image, 'run', '--auto', '--format', 'json',
                     '--model', agent_model]
            if variant:
                argv += ['--variant', variant]
            argv += [PROMPT]
            agent_started = time.monotonic()
            container_id = command(argv, timeout=60, output=setup_log).strip()
            try:
                waited = command(['docker', 'wait', container_id],
                                 timeout=seconds).strip()
                agent_exit = int(waited)
            except subprocess.TimeoutExpired:
                failure = 'time_budget'
                failure_category = 'budget'
                subprocess.run(['docker', 'kill', container_id],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30)
            agent_seconds = round(time.monotonic() - agent_started, 1)
            with log.open('w') as stream:
                result = subprocess.run(['docker', 'logs', container_id],
                                        stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=60)
            if result.returncode:
                raise RuntimeError('could not collect agent log')
            provider_error = _agent_error(log)
            if provider_error and agent_exit != 0:
                raise TransportError(provider_error)
            instruction_evidence = _instruction_evidence(log)
            process_checks['no_publish_attempt'] = not instruction_evidence[
                'publish_attempt_seen']
            session_id = _session_id(log)
            if session_id:
                export = ['docker', 'run', '--rm', '--network', 'none',
                          '--user', f'{os.getuid()}:{os.getgid()}',
                          '--read-only', '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=512m',
                          '-v', f'{candidate.resolve()}:/workspace:ro',
                          '-v', f'{home.resolve()}:/home/agent:rw',
                          '-e', 'HOME=/home/agent', '-e',
                          'OPENCODE_CONFIG=/home/agent/.config/opencode/opencode.json',
                          '-e', 'OPENCODE_CONFIG_DIR=/home/agent/.config/opencode',
                          agent_image, 'export', session_id]
                with session_export.open('w') as stream:
                    result = subprocess.run(export, stdout=stream,
                                            stderr=subprocess.PIPE, text=True,
                                            timeout=90)
                if result.returncode:
                    with setup_log.open('a') as stream:
                        stream.write('opencode export failed: '
                                     + result.stderr[-2000:] + '\n')
                    session_export.unlink(missing_ok=True)
                elif session_export.exists():
                    try:
                        json.loads(session_export.read_text())
                        export_complete = True
                    except ValueError:
                        export_complete = False
                        partial = session_export.with_suffix('.partial.json')
                        session_export.rename(partial)
                        session_export = partial
            observed = _model_events(session_export if session_export.exists()
                                     else log)
            if failure is None and agent_exit != 0:
                failure = f'agent_exit_{agent_exit}'
                failure_category = 'infrastructure'
            diff = subprocess.run(['git', '-C', str(candidate), 'diff', '--check'],
                                  text=True, capture_output=True, timeout=30)
            process_checks['diff_clean'] = diff.returncode == 0
            if diff.stdout or diff.stderr:
                with setup_log.open('a') as stream:
                    stream.write('git diff --check\n' + diff.stdout + diff.stderr)
            judged_at = time.monotonic()
            checks, details = grade(candidate, original, image)
            checks.update(process_checks)
            judge_seconds = round(time.monotonic() - judged_at, 1)
        except TransportError as exc:
            failure = f'transport_error: {exc}'
            failure_category = 'infrastructure'
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            failure = failure or f'harness_error: {exc}'
            failure_category = 'infrastructure'
        finally:
            if container_id:
                subprocess.run(['docker', 'rm', '-f', container_id],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30)

    model_match = bool(observed) and observed == [agent_model]
    if failure is None and not model_match:
        failure = 'model_mismatch' if observed else 'model_unverified'
        failure_category = 'infrastructure'
    artefact_passed = bool(checks) and all(checks.values()) and model_match
    finished = agent_exit == 0
    return {
        'task': 'arkade-add', 'category': 'coding',
        'interpretation': 'diagnostic_only', 'task_status': 'experimental',
        'harness': 'docker-opencode-native', 'suite_version': '0.8',
        'requested_model': model, 'agent_model': agent_model,
        'observed_models': observed, 'model_match': model_match,
        'arkade_revision': tasks.ARKADE_REVISION, 'prompt': PROMPT,
        'agent_variant': variant,
        'started_at': start, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': agent_seconds or 0, 'setup_seconds': setup_seconds,
        'judge_seconds': judge_seconds,
        'container_image_id': agent_image_id,
        'transcript': str(log) if log.exists() else None,
        'session_export': str(session_export) if session_export.exists() else None,
        'session_export_complete': export_complete,
        'setup_log': str(setup_log), 'agent_exit_code': agent_exit,
        'instruction_evidence': instruction_evidence,
        'checks': checks, 'acceptance': details,
        'artefact_passed': artefact_passed,
        'conversation_finished': finished,
        'passed': artefact_passed and finished and failure is None,
        'failure': failure, 'failure_category': failure_category,
    }
