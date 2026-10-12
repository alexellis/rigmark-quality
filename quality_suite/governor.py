"""Deterministic progress limits for agent-style quality tasks.

The governor sees public tool results, not hidden acceptance checks.  It may
send one recorded reminder before stopping an unchanged repetition pattern.
"""
from collections import Counter
import hashlib


class Governor:
    def __init__(self, task_id, workspace, editable):
        self.task_id = task_id
        self.workspace = workspace
        self.editable = editable
        self.repeated_reads = Counter()
        self.green_tests = Counter()
        self.notices = []
        self._seen_notices = set()

    def digest(self):
        h = hashlib.sha256()
        for name in sorted(self.editable):
            path = self.workspace / name
            h.update(name.encode())
            h.update(path.read_bytes() if path.exists() else b'')
        return h.hexdigest()

    def _notice(self, key, message):
        if key in self._seen_notices:
            return None
        self._seen_notices.add(key)
        self.notices.append({'kind': key, 'message': message})
        return message

    def observe(self, call):
        """Return (reminder, stop_reason) after a completed public tool call."""
        name, result = call['name'], call['result']
        digest = self.digest()
        if name in ('read_file', 'search_files', 'list_files'):
            key = (digest, name, call['arguments'])
            self.repeated_reads[key] += 1
            count = self.repeated_reads[key]
            if count == 3:
                return self._notice('repeated_read',
                    'Governor: this exact read/search returned unchanged data three times. '
                    'Use the evidence already available; make the requested change or finish.'), None
            if count >= 4:
                return None, 'no_progress: repeated unchanged read/search'
        if name == 'run_tests' and result.get('exit_code') == 0 and not result.get('timeout'):
            self.green_tests[digest] += 1
            count = self.green_tests[digest]
            if count == 2:
                return self._notice('repeated_green_test',
                    'Governor: public tests passed twice with no intervening edit. '
                    'Check the requested deliverables once and give your final answer. '
                    'Do not rerun the same passing test without new evidence.'), None
            if count >= 3:
                return None, 'no_progress: repeated passing tests without an edit'
        return None, None

    def exploration(self, step, edited):
        """Bound repository-reading loops on coding tasks."""
        if not self.editable or edited:
            return None, None
        if step == 25:
            return self._notice('exploration_budget',
                'Governor: 25 model turns have passed without an edit. '
                'Use the repository evidence gathered so far and implement the task.'), None
        if step >= 40:
            return None, 'no_progress: 40 model turns without an edit'
        return None, None
