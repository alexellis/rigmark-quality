import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
