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
        schema_before = {row[1]: row for row in conn.execute(
            'SELECT type, name, tbl_name, sql FROM sqlite_schema')}
        settings_before = tuple(conn.execute(f'PRAGMA {name}').fetchone()[0]
                                for name in ('foreign_keys', 'user_version',
                                             'recursive_triggers', 'automatic_index'))
        want = expected(conn, since)
        conn.executescript(Path('indexes.sql').read_text())
        schema_after = {row[1]: row for row in conn.execute(
            'SELECT type, name, tbl_name, sql FROM sqlite_schema')}
        self.assertEqual({name: schema_after.get(name) for name in schema_before},
                         schema_before, 'indexes.sql changed an existing schema object')
        for name, (kind, _, table, sql) in schema_after.items():
            if name not in schema_before:
                self.assertEqual(kind, 'index', 'indexes.sql added a non-index object')
                self.assertIn(table, ('orders', 'order_lines'))
                self.assertRegex(sql or '', r'(?i)^CREATE\s+INDEX\b')
        self.assertEqual(tuple(conn.execute(f'PRAGMA {name}').fetchone()[0]
                               for name in ('foreign_keys', 'user_version',
                                            'recursive_triggers', 'automatic_index')),
                         settings_before, 'indexes.sql changed a connection setting')
        for table, rows in before.items():
            self.assertEqual(conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall(), rows,
                             table + ' changed while adding indexes')
        query = Path('report.sql').read_text()
        cursor = conn.execute(query, {'since': since})
        self.assertEqual([column[0] for column in cursor.description],
                         ['customer_id', 'revenue_cents'])
        got = cursor.fetchall()
        self.assertEqual(got, want)
        conn.execute('ANALYZE')
        conn.execute('PRAGMA automatic_index = OFF')
        plan_rows = [row[3] for row in conn.execute(
            'EXPLAIN QUERY PLAN ' + query, {'since': since})]
        source_aliases = {'orders', 'order_lines'}
        for table, alias in re.findall(
                r'\b(?:FROM|JOIN)\s+(orders|order_lines)\s+(?:AS\s+)?([A-Za-z_]\w*)',
                query, re.I):
            source_aliases.add(alias.casefold())
        scans = [detail for detail in plan_rows
                 if (match := re.search(r'\bSCAN\s+(?:TABLE\s+)?([A-Za-z_]\w*)',
                                        detail, re.I))
                 and match.group(1).casefold() in source_aliases]
        self.assertFalse(scans, 'report scans a source table: ' + repr(scans))
        lookups = []
        for detail in plan_rows:
            match = re.search(r'\bSEARCH\b.*\bUSING (?:COVERING )?INDEX (.+?)\s*\(([^()]*)\)',
                              detail)
            if match:
                name = match.group(1).strip()
                if (len(name) >= 2 and
                        ((name[0] == name[-1] and name[0] in ('"', "'", '`'))
                         or (name[0] == '[' and name[-1] == ']'))):
                    name = name[1:-1]
                lookups.append((name, match.group(2)))
        plan = '\n'.join(plan_rows)
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(orders)')}
        definitions = dict(conn.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type='index' AND tbl_name='orders'"))
        # SQLite renders both >= and > as >? in EXPLAIN QUERY PLAN. The
        # boundary result above distinguishes their semantics. A partial
        # index WHERE status='paid' supplies the status filter without a
        # status=? term in the plan.
        ordered_on = r'\bordered_on\s*>\s*\?'
        def paid_only_index(name):
            definition = definitions.get(name) or ''
            predicate = re.search(r'\bWHERE\b(.*)$', definition, re.I | re.S)
            if not predicate or re.search(r'\bOR\b', predicate.group(1), re.I):
                return False
            if not re.search(r"\bstatus\s*=\s*['\"]paid['\"]",
                             predicate.group(1), re.I):
                return False
            quoted = '"' + name.replace('"', '""') + '"'
            query = ('EXPLAIN QUERY PLAN SELECT id FROM orders INDEXED BY '
                     + quoted + " WHERE status = 'paid' AND ordered_on >= ? "
                     'AND ordered_on IS NOT NULL')
            try:
                conn.execute(query, (since,)).fetchall()
            except sqlite3.OperationalError:
                return False
            try:
                conn.execute(query.replace("status = 'paid'", "status = 'pending'"),
                             (since,)).fetchall()
            except sqlite3.OperationalError:
                return True
            return False
        self.assertTrue(any(
            name in indexes and re.search(ordered_on, terms)
            and (re.search(r'\bstatus\s*=\s*\?', terms)
                 or paid_only_index(name))
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
