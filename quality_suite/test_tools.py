import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from . import advanced_evaluators, advanced_tasks, cli, runtime, tasks
from .tools import ToolBox


class FileSearchTests(unittest.TestCase):
    def test_literal_search_tolerates_go_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'candidate.go').write_text('Name:       "yq"\nName: "shfmt"\n')
            box = ToolBox('python-expiry', root, 'unused')
            result = box.call('search_files', json.dumps({
                'path': 'candidate.go', 'text': 'Name: "yq"'}))
            self.assertEqual(result['matches'], ['1: Name:       "yq"'])
            self.assertEqual(box.call('search_files', json.dumps({
                'path': 'candidate.go', 'text': 'name: "yq"'})),
                             {'matches': []})
            self.assertEqual(box.call('search_files', json.dumps({
                'path': '.', 'text': 'Name: "yq"'})),
                             {'matches': ['candidate.go:1: Name:       "yq"']})
            self.assertEqual(box.call('list_files', '{}'),
                             {'files': ['candidate.go']})


class BaselineTestTests(unittest.TestCase):
    def test_go_assertion_message_can_improve(self):
        original = tasks.TASKS['go-export-boundary']['files']['server_test.go']
        candidate = original.replace('status %d', 'status %d, want 200')
        baseline = cli.compact_test(cli.test_body(original, 'TestOwnerCanRead'))
        changed = cli.compact_test(cli.test_body(candidate, 'TestOwnerCanRead'))
        self.assertIn(baseline, changed)
        without_assertion = candidate.replace(
            'if w.Code != http.StatusOK { t.Fatalf("status %d, want 200", w.Code) }',
            '')
        changed = cli.compact_test(cli.test_body(without_assertion, 'TestOwnerCanRead'))
        self.assertNotIn(baseline, changed)

    def test_sqlite_acceptance_needs_terminal_events(self):
        output = ('test_large_repetitive_seed '
                  '(sqlite_report_acceptance.Acceptance.test_large_repetitive_seed) '
                  '... ok\n'
                  'test_different_seed_and_date '
                  '(sqlite_report_acceptance.Acceptance.test_different_seed_and_date) '
                  '... ok\n\n----------------------------------------------------------------------\n'
                  'Ran 2 tests in 0.2s\n\nOK\n')
        self.assertTrue(cli.hidden_python_suite_passed(
            {'terminal_events': runtime.terminal_events(io.BytesIO(output.encode()))},
                                                       'sqlite-report'))
        self.assertFalse(cli.hidden_python_suite_passed(
            {'terminal_events': runtime.terminal_events(io.BytesIO(b''))},
                                                        'sqlite-report'))


class PublicTestIsolationTests(unittest.TestCase):
    def test_test_time_changes_do_not_reach_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'schema.py').write_text('trusted fixture')
            box = ToolBox('python-expiry', root, 'unused')

            def mutate_copy(candidate, image, command, timeout):
                (candidate / 'schema.py').write_text('candidate mutation')
                return {'exit_code': 0, 'timeout': False, 'output': ''}

            with mock.patch('quality_suite.runtime.run', side_effect=mutate_copy):
                box.call('run_tests', '{}')
            self.assertEqual((root / 'schema.py').read_text(), 'trusted fixture')

    def test_long_output_retains_terminal_result(self):
        result = runtime.capture(['python3', '-c',
                                  'print("start"); print("x" * 70000); '
                                  'print("terminal verdict")'])
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('start', result['output'])
        self.assertIn('terminal verdict', result['output'])
        self.assertIn('[intermediate output omitted]', result['output'])

    def test_grading_event_survives_truncated_middle(self):
        result = runtime.capture(['python3', '-c',
                                  'print("x" * 40000); '
                                  'print("test_case (suite.Acceptance.test_case) ... ok"); '
                                  'print("x" * 40000); '
                                  'print("Ran 1 test in 0.1s\\n\\nOK")'])
        self.assertNotIn('suite.Acceptance.test_case', result['output'])
        self.assertIn('suite.Acceptance.test_case',
                      result['terminal_events']['python_pass'])

    def test_subtest_failure_keeps_parent_test_id(self):
        output = ("FAIL: test_case (test_report.Case.test_case) "
                  "(since='2026-10-01')\n")
        events = runtime.terminal_events(io.BytesIO(output.encode()))
        self.assertIn('test_report.Case.test_case', events['python_failed'])


class ReviewGradeTests(unittest.TestCase):
    def review_calls(self, directory, partial=None):
        root = Path(directory)
        files = advanced_tasks.TASK_DEFINITIONS['go-concurrency-review']['files']
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        box = ToolBox('go-concurrency-review', root, 'unused')
        for name in files:
            if name.endswith('.go'):
                box.call('read_file', json.dumps({
                    'path': name, 'offset': 0,
                    'limit': 1 if name == partial else 250}))
        return box.calls

    def test_formatting_does_not_erase_correct_diagnosis(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.review_calls(directory)
            self.assertTrue(self.grade_reference(calls)['inspected_both'])
        answer = json.dumps(advanced_tasks.REVIEW_REFERENCE)
        for variant, expected_format in (
            (answer, 'plain_json'),
            ('```json\n' + answer + '\n```', 'fenced_json'),
            ('```json\n' + answer + '\n```\nA separate note.',
             'fenced_with_commentary'),
        ):
            with self.subTest(expected_format=expected_format):
                self.assertEqual(advanced_evaluators.review_format(variant),
                                 expected_format)
                self.assertTrue(all(advanced_evaluators.grade_review(variant, calls).values()))

    def grade_reference(self, calls):
        return advanced_evaluators.grade_review(
            json.dumps(advanced_tasks.REVIEW_REFERENCE), calls)

    def test_failed_and_partial_reads_do_not_count(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.review_calls(directory)
            failed = [dict(call) for call in calls]
            failed[0]['result'] = {'error': 'file not found', 'kind': 'invalid_tool_call'}
            self.assertFalse(self.grade_reference(failed)['inspected_both'])
            partial = self.review_calls(directory, partial='candidate_b/dispatcher.go')
            self.assertFalse(self.grade_reference(partial)['inspected_both'])

    def test_safe_claim_cannot_pass_causal_review(self):
        evidence = ('Submit reads wasClosed=false, then unlocks. Close closes jobs. '
                    'Submit sends to the channel, but candidate B is safe and '
                    'does not panic.')
        for kind in ('sound', 'send_on_closed_channel'):
            with self.subTest(kind=kind):
                answer = json.dumps({'findings': [{
                    'file': 'candidate_b/dispatcher.go', 'kind': kind,
                    'evidence': evidence}],
                    'clear': ['candidate_a/dispatcher.go']})
                checks = advanced_evaluators.grade_review(answer, [])
                self.assertFalse(checks['causal_evidence'])
                if kind == 'sound':
                    self.assertFalse(checks['real_issue'])

    def test_denied_send_or_crash_cannot_pass_causal_review(self):
        prefix = 'Submit unlocks. Close closes the jobs channel. '
        for ending in ('Submit does not send, so there is no crash.',
                       'Submit cannot enqueue, so it does not panic.',
                       'Submit won\'t send, so there is no crash.',
                       'Submit never sends and cannot crash.'):
            with self.subTest(ending=ending):
                self.assertFalse(advanced_evaluators.review_cause(
                    'send-on-closed-channel race', prefix + ending))

    def test_mutex_does_not_cover_send_is_valid_evidence(self):
        evidence = ('Submit unlocks after checking the closed flag. Close '
                    'closes jobs. Submit then sends to jobs and panics. '
                    'The mutex does not cover the send.')
        self.assertTrue(advanced_evaluators.review_cause(
            'send-on-closed-channel race', evidence))

    def test_causal_review_accepts_equivalent_verbs(self):
        for verb in ('checks', 'sees', 'loads'):
            with self.subTest(verb=verb):
                evidence = (f'Submit {verb} wasClosed == false, then unlocks. '
                            'Close closes jobs before Submit sends to jobs, '
                            'so Submit panics on the closed channel.')
                self.assertTrue(advanced_evaluators.review_cause(
                    'send_on_closed_channel', evidence))

    def test_causal_review_accepts_unlock_before_interleaving(self):
        evidence = ('Submit reads wasClosed under the mutex, then unlocks before '
                    'sending to jobs. Interleaving: Submit reads wasClosed=false; '
                    'Close closes jobs; Submit sends to the closed channel and '
                    'panics with send on closed channel.')
        self.assertTrue(advanced_evaluators.review_cause(
            'send_on_closed_channel', evidence))

    def test_causal_review_accepts_channel_close_race(self):
        evidence = ('Submit observes the dispatcher open, then unlocks. '
                    'Close closes jobs; Submit sends to the closed channel '
                    'and panics.')
        self.assertTrue(advanced_evaluators.review_cause(
            'channel-close race', evidence))

    def test_causal_review_accepts_queue_vocabulary(self):
        evidence = ('Submit drops the mutex after checking the dispatcher is open. '
                    'Close shuts the queue, and the later enqueue crashes because '
                    'the jobs channel is closed.')
        self.assertTrue(advanced_evaluators.review_cause(
            'send_on_closed_jobs', evidence))

    def test_causal_review_accepts_close_first_clause(self):
        evidence = ('Close closes jobs after Submit observes the dispatcher open '
                    'and unlocks; Submit then sends to the closed channel and panics.')
        self.assertTrue(advanced_evaluators.review_cause(
            'TOCTOU shutdown race', evidence))

    def test_causal_review_uses_send_after_close(self):
        evidence = ('Submit releases the mutex after reading wasClosed and '
                    'performs a send outside the lock. Interleaving: Submit '
                    'reads closed=false and unlocks; Close sets closed=true '
                    'and close(d.jobs); Submit then sends to the closed '
                    'channel, panicking.')
        self.assertTrue(advanced_evaluators.review_cause(
            'send-on-closed-channel panic', evidence))

    def test_false_positive_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = self.review_calls(directory)
        answer = json.dumps({'findings': [{
            'file': 'candidate_a/dispatcher.go', 'kind': 'race',
            'evidence': 'Submit and Close can race on the channel.'}],
            'clear': ['candidate_b/dispatcher.go']})
        checks = advanced_evaluators.grade_review(answer, calls)
        self.assertFalse(checks['real_issue'])
        self.assertFalse(checks['no_false_positive'])


if __name__ == '__main__':
    unittest.main()
