import json
import tempfile
import unittest
from pathlib import Path

from . import advanced_evaluators, advanced_tasks
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


class ReviewGradeTests(unittest.TestCase):
    def test_formatting_does_not_erase_correct_diagnosis(self):
        calls = [{'name': 'read_file', 'arguments': json.dumps({'path': name})}
                 for name in advanced_tasks.TASK_DEFINITIONS['go-concurrency-review']['files']
                 if name.endswith('.go')]
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
                self.assertTrue(all(advanced_evaluators.grade_review(
                    variant, calls).values()))

    def test_false_positive_fails(self):
        calls = [{'name': 'read_file', 'arguments': json.dumps({'path': name})}
                 for name in advanced_tasks.TASK_DEFINITIONS['go-concurrency-review']['files']
                 if name.endswith('.go')]
        answer = json.dumps({'findings': [{
            'file': 'candidate_a/dispatcher.go', 'kind': 'race',
            'evidence': 'Submit and Close can race on the channel.'}],
            'clear': ['candidate_b/dispatcher.go']})
        checks = advanced_evaluators.grade_review(answer, calls)
        self.assertFalse(checks['real_issue'])
        self.assertFalse(checks['no_false_positive'])


if __name__ == '__main__':
    unittest.main()
