import json
import tempfile
import unittest
from pathlib import Path

from . import cli
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


class CandidateLinkTests(unittest.TestCase):
    def test_grading_does_not_follow_planted_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host_file = root / 'host-secret.txt'
            host_file.write_text('not for the judge\n')
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'expiry.py').symlink_to(host_file)
            copy = root / 'copy'
            cli.copy_workspace(workspace, copy)
            self.assertTrue((copy / 'expiry.py').is_symlink())
            self.assertEqual(cli.read_candidate_text(workspace / 'expiry.py'), '')
            self.assertEqual(cli.read_candidate_text(workspace / 'missing.py'), '')


if __name__ == '__main__':
    unittest.main()
