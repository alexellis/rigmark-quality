"""Independent correctness and query-plan checks for the SQLite report."""
from collections import defaultdict
from pathlib import Path
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
        plan = '\n'.join(row[3] for row in conn.execute(
            'EXPLAIN QUERY PLAN ' + query, {'since': since}))
        for table in ('orders', 'order_lines'):
            indexes = [row[1] for row in conn.execute(f'PRAGMA index_list({table})')]
            self.assertTrue(indexes, table + ' lacks an index')
            self.assertTrue(any(name in plan for name in indexes),
                            table + ' has no indexed lookup in query plan:\n' + plan)

    def test_large_repetitive_seed(self):
        self.check_case(317, 50000, 17, '2026-10-01')

    def test_different_seed_and_date(self):
        self.check_case(97, 2400, 31, '2026-08-15')


if __name__ == '__main__':
    unittest.main()
