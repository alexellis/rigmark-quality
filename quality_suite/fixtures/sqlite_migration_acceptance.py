"""Independent checks injected after the SQLite migration attempt."""
import sqlite3
import unittest
from collections import Counter

from migration import migrate
from schema import LEGACY_SCHEMA


def legacy_connection():
    conn = sqlite3.connect(':memory:')
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(LEGACY_SCHEMA)
    return conn


def tables(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def state(conn):
    schema = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "ORDER BY type, name").fetchall()
    rows = {table: Counter(conn.execute(f'SELECT * FROM "{table}"').fetchall())
            for table in tables(conn)}
    return (schema, rows, conn.execute('PRAGMA user_version').fetchone()[0],
            conn.execute('PRAGMA foreign_keys').fetchone()[0],
            conn.execute('PRAGMA foreign_key_list(invoice_items)').fetchall()
            if 'invoice_items' in rows else [])


def unrelated_state(conn):
    names = tables(conn) - {'invoice_lines', 'invoices', 'invoice_items'}
    objects = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE tbl_name NOT IN ('invoice_lines', 'invoices', 'invoice_items') "
        "ORDER BY type, name").fetchall()
    rows = {table: Counter(conn.execute(f'SELECT * FROM "{table}"').fetchall())
            for table in names}
    return objects, rows


def require_columns(conn, table, expected):
    def affinity(declared):
        declared = declared.upper()
        if 'INT' in declared:
            return 'INTEGER'
        if any(word in declared for word in ('CHAR', 'CLOB', 'TEXT')):
            return 'TEXT'
        return declared
    actual = {row[1]: (affinity(row[2]), bool(row[3]), row[5])
              for row in conn.execute(f'PRAGMA table_xinfo("{table}")')}
    if set(actual) != set(expected):
        raise AssertionError(f'{table} columns: {actual!r} != {expected!r}')
    for name, (kind, required_not_null, pk) in expected.items():
        got_kind, got_not_null, got_pk = actual[name]
        if (got_kind != kind or got_pk != pk
                or (required_not_null and not got_not_null)):
            raise AssertionError(f'{table}.{name}: {actual[name]!r} != {expected[name]!r}')


class Acceptance(unittest.TestCase):
    def test_every_line_and_other_table_survive(self):
        conn = legacy_connection()
        rows = []
        for invoice in range(1, 51):
            for part in range(1, 4):
                rows.append((invoice * 10 + part, f'INV-{invoice:03d}',
                             f'Name+{invoice}@example.test', '2026-10-02',
                             invoice * 17, f'SKU-{part % 2}', part,
                             -25 if part == 3 else invoice * part))
        rows.append((9001, 'INV-special', 'a+b@example.test',
                     '2024-02-29', 0, 'ZERO', 1, 0))
        conn.executemany('INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?)', rows)
        conn.execute("INSERT INTO audit_log VALUES (4, 'retain exactly')")
        conn.execute('CREATE UNIQUE INDEX audit_note_unique ON audit_log(note)')
        conn.execute("CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log "
                     "BEGIN SELECT RAISE(ABORT, 'audit protected'); END")
        conn.commit()
        unrelated_before = unrelated_state(conn)

        migrate(conn)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertTrue({'invoices', 'invoice_items'} <= tables(conn))
        self.assertNotIn('invoice_lines', tables(conn))
        foreign_keys = {(row[3], row[2], row[4]) for row in conn.execute(
            'PRAGMA foreign_key_list(invoice_items)')}
        self.assertEqual(foreign_keys, {('invoice_id', 'invoices', 'invoice_id')})
        require_columns(conn, 'invoices', {
            'invoice_id': ('TEXT', True, 1),
            'customer_email': ('TEXT', True, 0),
            'issued_on': ('TEXT', True, 0),
            'paid_cents': ('INTEGER', True, 0),
        })
        require_columns(conn, 'invoice_items', {
            'line_id': ('INTEGER', False, 1),
            'invoice_id': ('TEXT', True, 0),
            'sku': ('TEXT', True, 0),
            'quantity': ('INTEGER', True, 0),
            'unit_cents': ('INTEGER', True, 0),
        })
        self.assertEqual(unrelated_state(conn), unrelated_before)
        self.assertEqual(conn.execute('SELECT * FROM audit_log').fetchall(),
                         [(4, 'retain exactly')])
        self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 51)
        self.assertEqual(conn.execute('SELECT line_id, invoice_id, sku, quantity, unit_cents '
                                      'FROM invoice_items ORDER BY line_id').fetchall(),
                         [(r[0], r[1], r[5], r[6], r[7])
                          for r in sorted(rows)])
        self.assertEqual(conn.execute('SELECT invoice_id, customer_email, issued_on, paid_cents '
                                      'FROM invoices ORDER BY invoice_id').fetchall(),
                         sorted({(r[1], r[2], r[3], r[4]) for r in rows}))
        before = state(conn)
        migrate(conn)
        self.assertEqual(state(conn), before)

    def test_conflicting_metadata_rolls_back_everything(self):
        for field, replacement in (('customer_email', 'second@example.test'),
                                   ('issued_on', '2026-10-02'),
                                   ('paid_cents', 501)):
            with self.subTest(field=field):
                conn = legacy_connection()
                first = (17, 'INV-X', 'first@example.test', '2026-10-01', 500, 'A', 1, 500)
                second = [29, 'INV-X', 'first@example.test', '2026-10-01', 500, 'B', 1, 0]
                second[{'customer_email': 2, 'issued_on': 3, 'paid_cents': 4}[field]] = replacement
                rows = [first, tuple(second)]
                conn.executemany('INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?)', rows)
                conn.execute("INSERT INTO audit_log VALUES (7, 'retain')")
                conn.commit()
                conn.execute("INSERT INTO audit_log VALUES (8, 'caller work')")
                with self.assertRaises(Exception):
                    migrate(conn)
                self.assertEqual(tables(conn), {'invoice_lines', 'audit_log'})
                self.assertEqual(conn.execute('SELECT * FROM invoice_lines ORDER BY line_id').fetchall(), rows)
                self.assertEqual(conn.execute('SELECT * FROM audit_log ORDER BY rowid').fetchall(),
                                 [(7, 'retain'), (8, 'caller work')])
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 0)
                conn.rollback()
                self.assertEqual(conn.execute('SELECT * FROM audit_log').fetchall(),
                                 [(7, 'retain')])

    def test_caller_can_roll_back_migration(self):
        conn = legacy_connection()
        before = state(conn)
        conn.execute("INSERT INTO invoice_lines VALUES (8, 'INV-R', 'r@example.test', '2026-10-01', 10, 'R', 1, 10)")
        conn.execute("INSERT INTO audit_log VALUES (9, 'caller transaction')")
        migrate(conn)
        self.assertEqual(conn.execute('SELECT * FROM invoices').fetchall(),
                         [('INV-R', 'r@example.test', '2026-10-01', 10)])
        self.assertEqual(conn.execute('SELECT * FROM invoice_items').fetchall(),
                         [(8, 'INV-R', 'R', 1, 10)])
        self.assertEqual(conn.execute('SELECT * FROM audit_log').fetchall(),
                         [(9, 'caller transaction')])
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
        conn.rollback()
        self.assertEqual(state(conn), before)


if __name__ == '__main__':
    unittest.main()
