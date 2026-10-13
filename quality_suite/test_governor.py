import tempfile
import unittest
from pathlib import Path

from .governor import Governor


class GovernorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'candidate.go').write_text('before')
        self.guard = Governor('go-example', self.root, ['candidate.go'])

    def test_repeated_read_stops_only_when_workspace_is_unchanged(self):
        call = {'name': 'search_files', 'arguments': '{"path":"candidate.go","text":"Run"}',
                'result': {'matches': []}}
        self.assertEqual(self.guard.observe(call), (None, None))
        self.assertEqual(self.guard.observe(call), (None, None))
        reminder, stop = self.guard.observe(call)
        self.assertIn('unchanged data', reminder)
        self.assertIsNone(stop)
        (self.root / 'candidate.go').write_text('after')
        self.assertEqual(self.guard.observe(call), (None, None))
        for _ in range(2):
            self.guard.observe(call)
        self.assertEqual(self.guard.observe(call)[1],
                         'no_progress: repeated unchanged read/search')

    def test_repeated_green_tests_remind_without_stopping(self):
        call = {'name': 'run_tests', 'arguments': '{}',
                'result': {'exit_code': 0, 'timeout': False}}
        self.assertEqual(self.guard.observe(call), (None, None))
        reminder, stop = self.guard.observe(call)
        self.assertIn('public tests passed twice', reminder)
        self.assertIsNone(stop)
        (self.root / 'candidate.go').write_text('after')
        self.assertEqual(self.guard.observe(call), (None, None))
        self.assertEqual(self.guard.observe(call)[1], None)
        self.assertEqual(self.guard.observe(call), (None, None))

    def test_exploration_reminds_without_a_turn_limit(self):
        reminder, stop = self.guard.exploration(25, False)
        self.assertIsNone(stop)
        self.assertIn('25 model turns', reminder or '')
        self.assertEqual(self.guard.exploration(40, False), (None, None))
        self.assertEqual(self.guard.exploration(100, False), (None, None))

    def test_failed_tests_do_not_count_as_green(self):
        call = {'name': 'run_tests', 'arguments': '{}',
                'result': {'exit_code': 1, 'timeout': False}}
        for _ in range(5):
            self.assertEqual(self.guard.observe(call), (None, None))


if __name__ == '__main__':
    unittest.main()
