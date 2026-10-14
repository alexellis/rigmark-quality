"""Local controls for the native-agent receipt and grading inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from . import native_arkade


class NativeArkadeTests(unittest.TestCase):
    def test_export_identifies_provider_and_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            path.write_text(json.dumps({'messages': [
                {'info': {'role': 'assistant', 'providerID': 'toilgate',
                          'modelID': 'deepseek-v4-flash-0731'}},
                {'info': {'role': 'assistant', 'providerID': 'toilgate',
                          'modelID': 'deepseek-v4-flash-0731'}},
            ]}))
            self.assertEqual(native_arkade._model_events(path),
                             ['toilgate/deepseek-v4-flash-0731'])

    def test_incomplete_export_uses_session_and_message_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            path.write_text('{"info":{"model":{"id":"glm-5.3-flash",'
                            '"providerID":"toilgate"}},"messages":['
                            '{"info":{"providerID":"toilgate",'
                            '"modelID":"glm-5.3-flash"}},'
                            '{"info":{"providerID":"toilgate",'
                            '"modelID":"other"}},"unfinished')
            self.assertEqual(native_arkade._model_events(path),
                             ['toilgate/glm-5.3-flash', 'toilgate/other'])

    def test_primary_and_small_model_are_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'opencode.json'
            source.write_text(json.dumps({'model': 'toilgate/other',
                                          'small_model': 'toilgate/other',
                                          'provider': {'toilgate': {'name': 'Toilgate'}}}))
            pinned = native_arkade._pinned_config('toilgate/contender', source)
            try:
                config = json.loads(pinned.read_text())
                self.assertEqual(config['model'], 'toilgate/contender')
                self.assertEqual(config['small_model'], 'toilgate/contender')
                self.assertIn('toilgate', config['provider'])
            finally:
                pinned.unlink()

    def test_portable_agent_keeps_only_selected_provider_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'source.json'
            config.write_text(json.dumps({
                'model': 'other/model', 'mcp': {'host-only': {}},
                'provider': {'toilgate': {'npm': 'selected'},
                             'other': {'npm': 'not-selected'}},
            }))
            destination = root / 'config.json'
            native_arkade._portable_config('toilgate/model', config, destination)
            result = json.loads(destination.read_text())
            self.assertEqual(result['model'], 'toilgate/model')
            self.assertEqual(result['small_model'], 'toilgate/model')
            self.assertEqual(result['provider'], {'toilgate': {'npm': 'selected'}})
            self.assertNotIn('mcp', result)

            auth = root / 'auth-source.json'
            auth.write_text(json.dumps({'toilgate': {'key': 'selected'},
                                        'other': {'key': 'not-selected'}}))
            target = root / 'home/.local/share/opencode/auth.json'
            self.assertTrue(native_arkade._portable_auth(
                'toilgate/model', auth, target))
            self.assertEqual(json.loads(target.read_text()),
                             {'toilgate': {'key': 'selected'}})

    def test_portable_agent_allows_builtin_provider_without_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'opencode.json'
            native_arkade._portable_config('opencode/free-model',
                                           root / 'missing.json', target)
            self.assertEqual(json.loads(target.read_text()), {
                'model': 'opencode/free-model',
                'small_model': 'opencode/free-model',
            })

    def test_native_grader_rejects_candidate_symlinks_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / 'candidate'
            candidate.mkdir()
            (candidate / 'README.md').symlink_to('/etc/passwd')
            checks, details = native_arkade.grade(candidate, root, 'unused')
            self.assertEqual(checks, {'candidate_has_no_symlinks': False})
            self.assertEqual(details, {'symlink_paths': ['README.md']})

    def test_provider_error_is_not_a_coding_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.jsonl'
            path.write_text('# started\n\a\a' + json.dumps({
                'type': 'error', 'error': {'data': {
                    'message': 'Unexpected server error.'}}}) + '\n# exit code=1\n')
            self.assertEqual(native_arkade._agent_error(path),
                             'Unexpected server error.')

    def test_instruction_evidence_requires_successful_download_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.jsonl'
            events = [
                {'type': 'tool_use', 'part': {'state': {
                    'status': 'completed', 'input': {'command':
                    'curl -I https://github.com/mvdan/sh/releases/latest'},
                    'metadata': {'exit': 0}}}},
                {'type': 'tool_use', 'part': {'state': {
                    'status': 'completed', 'input': {'command':
                    './hack/test-tool.sh shfmt'}, 'metadata': {'exit': 127}}}},
                {'type': 'tool_use', 'part': {'state': {
                    'status': 'completed', 'input': {'command':
                    './hack/test-tool.sh shfmt'}, 'metadata': {'exit': 0}}}},
            ]
            path.write_text('\n'.join(json.dumps(event) for event in events))
            self.assertEqual(native_arkade._instruction_evidence(path), {
                'release_lookup_seen': True,
                'platform_download_script_passed': True,
                'publish_attempt_seen': False,
            })

    def test_changed_existing_test_file_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original' / 'pkg/get'
            candidate = root / 'candidate' / 'pkg/get'
            original.mkdir(parents=True)
            candidate.mkdir(parents=True)
            (original / 'get_test.go').write_text('package get\n')
            (candidate / 'get_test.go').write_text(
                'package get\nfunc TestShfmt(t *testing.T) {}\n')
            self.assertEqual(native_arkade.changed_go_files(
                root / 'candidate', root / 'original'),
                ['pkg/get/get_test.go'])


if __name__ == '__main__':
    unittest.main()
