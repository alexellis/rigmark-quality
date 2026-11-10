"""Independent correctness and query-plan checks for the SQLite report."""
from collections import defaultdict
from pathlib import Path
import re
import sqlite3
import unittest

from report_fixture import seed


def expected(conn, since):
    totals = defaultdict(int)
    for customer_id, status, ordered_on, quantity, unit_cents in conn.execute(
            'SELECT o.customer_id, o.status, o.ordered_on, li.quantity, li.unit_cents '
            'FROM orders AS o JOIN order_lines AS li ON li.order_id = o.id'):
        if status == 'paid' and ordered_on >= since:
            totals[customer_id] += quantity * unit_cents
    return sorted(totals.items(), key=lambda row: (-row[1], row[0]))[:10]


class Acceptance(unittest.TestCase):
    def check_case(self, customers, orders, salt, since):
        conn = sqlite3.connect(':memory:')
        seed(conn, customers, orders, salt)
        # A paid order on the boundary must be included. Its amount changes
        # the top result, so an exclusive date filter cannot pass by chance.
        conn.execute('INSERT INTO orders VALUES (?, ?, ?, ?)',
                     (orders + 1, 1, 'paid', since))
        conn.execute('INSERT INTO order_lines VALUES (?, ?, ?, ?, ?)',
                     (2 * orders + 1, orders + 1, 'BOUNDARY', 1, 1000000000))
        before = {table: conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                  for table in ('customers', 'orders', 'order_lines')}
        want = expected(conn, since)
        conn.executescript(Path('indexes.sql').read_text())
        for table, rows in before.items():
            self.assertEqual(conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall(), rows,
                             table + ' changed while adding indexes')
        query = Path('report.sql').read_text()
        got = conn.execute(query, {'since': since}).fetchall()
        self.assertEqual(got, want)
        conn.execute('ANALYZE')
        conn.execute('PRAGMA automatic_index = OFF')
        plan_rows = [row[3] for row in conn.execute(
            'EXPLAIN QUERY PLAN ' + query, {'since': since})]
        lookups = []
        for detail in plan_rows:
            match = re.search(r'\bSEARCH\b.*\bUSING (?:COVERING )?INDEX ([^\s(]+)\s*\(([^)]*)\)',
                              detail)
            if match:
                lookups.append((match.group(1), match.group(2)))
        plan = '\n'.join(plan_rows)
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(orders)')}
        definitions = dict(conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='orders'"))
        # SQLite renders both >= and > as >? in EXPLAIN QUERY PLAN. The
        # boundary result above distinguishes their semantics. A partial
        # index WHERE status='paid' supplies the status filter without a
        # status=? term in the plan.
        ordered_on = r'\bordered_on\s*>\s*\?'
        paid_predicate = r"\bWHERE\s+status\s*=\s*['\"]paid['\"]"
        self.assertTrue(any(
            name in indexes and re.search(ordered_on, terms)
            and (re.search(r'\bstatus\s*=\s*\?', terms)
                 or re.search(paid_predicate, definitions.get(name) or '', re.I))
            for name, terms in lookups),
            'orders has no indexed lookup on paid status and date:\n' + plan)
        line_indexes = {row[1] for row in conn.execute('PRAGMA index_list(order_lines)')}
        self.assertTrue(any(name in line_indexes and re.search(r'\border_id\s*=\s*\?', terms)
                            for name, terms in lookups),
                        'order_lines has no indexed order_id lookup:\n' + plan)

    def test_large_repetitive_seed(self):
        self.check_case(317, 50000, 17, '2026-10-01')

    def test_different_seed_and_date(self):
        self.check_case(97, 2400, 31, '2026-08-15')


if __name__ == '__main__':
    unittest.main()
