"""Checks that public resolution rates never hide incomplete or invalid runs."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import cli


FIXTURES = (Path(__file__).resolve().parent.parent / 'examples' / 'receipts'
            / '2026-10-13-protocol-06')


def receipts(model):
    return [data for path in FIXTURES.glob('*.json')
            if (data := json.loads(path.read_text()))['requested_model'] == model]


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.run = receipts('deepseek-v4-flash-0731')

    def test_complete_historical_run(self):
        result = cli.resolution(self.run)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['resolved'], result['total'], result['rate_percent']),
                         (11, 13, 85))

    def test_json_report_uses_same_resolution(self):
        output = io.StringIO()
        with redirect_stdout(output):
            cli.report(FIXTURES, format='json')
        runs = json.loads(output.getvalue())['runs']
        deepseek = next(run for run in runs
                        if run['requested_model'] == 'deepseek-v4-flash-0731')
        self.assertEqual(deepseek['resolution']['rate_percent'], 85)

    def test_partial_run_has_no_rate(self):
        result = cli.resolution(self.run[:-1])
        self.assertEqual(result['status'], 'incomplete')
        self.assertIsNone(result['rate_percent'])

    def test_duplicate_run_has_no_rate(self):
        result = cli.resolution(self.run + [self.run[0]])
        self.assertEqual(result['status'], 'invalid')
        self.assertIsNone(result['rate_percent'])

    def test_transport_and_model_errors_have_no_rate(self):
        for change in ({'model_match': False},
                       {'failure': 'HTTPError: HTTP Error 502: Bad Gateway'},
                       {'failure': "KeyError: 'choices'"},
                       {'failure_category': 'infrastructure'}):
            with self.subTest(change=change):
                run = copy.deepcopy(self.run)
                run[0].update(change)
                result = cli.resolution(run)
                self.assertEqual(result['status'], 'invalid')
                self.assertIsNone(result['rate_percent'])

    def test_malformed_response_after_a_successful_turn_is_invalid(self):
        model = 'deepseek-v4-flash-0731'
        first = {'model': model, 'choices': [{
            'message': {'role': 'assistant', 'content': '', 'tool_calls': [{
                'id': 'read-1', 'function': {
                    'name': 'stock_read', 'arguments': '{}'}}]},
            'finish_reason': 'tool_calls'}]}
        malformed = {'model': model, 'choices': []}
        with TemporaryDirectory() as directory:
            with (patch.object(cli, 'completion', side_effect=[first, malformed]),
                  patch.object(cli.runtime, 'image_id', return_value='test-image')):
                attempt = cli.run_task('stock-transfer', model, Path(directory),
                                       Path(directory), 'unused', 'http://unused/v1',
                                       'none', 0, 60, 'low', 'default')
        self.assertTrue(attempt['model_match'])
        self.assertEqual(attempt['failure_category'], 'infrastructure')
        run = copy.deepcopy(self.run)
        run[next(i for i, r in enumerate(run) if r['task'] == 'stock-transfer')] = attempt
        self.assertEqual(cli.resolution(run)['status'], 'invalid')

    def test_correct_artefact_without_completion_is_unsolved(self):
        run = copy.deepcopy(self.run)
        resolved = next(r for r in run if r['passed'])
        resolved.update(passed=False, artefact_passed=True,
                        conversation_finished=False, failure='time_budget')
        result = cli.resolution(run)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['resolved'], result['rate_percent']), (10, 77))

    def test_pilot_without_fixed_task_manifest_is_unscored(self):
        pilot = (FIXTURES.parent / '2026-10-11-pilot')
        run = [data for path in pilot.glob('*.json')
               if (data := json.loads(path.read_text()))['requested_model']
               == 'deepseek-v4-flash-0731']
        result = cli.resolution(run)
        self.assertEqual(result['status'], 'unscored')
        self.assertIsNone(result['rate_percent'])


if __name__ == '__main__':
    unittest.main()
