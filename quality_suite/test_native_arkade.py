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
