"""SQLite checks whose assertions run outside the candidate Python process."""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from schema import LEGACY_SCHEMA


CHILD = '''import sqlite3, sys
from migration import migrate
path, operation = sys.argv[1:]
conn = sqlite3.connect(path)
conn.execute('PRAGMA foreign_keys = ON')
if operation == 'rollback':
    conn.execute("INSERT INTO invoice_lines VALUES (8, 'INV-R', 'r@example.test', '2026-10-01', 10, 'R', 1, 10)")
    conn.execute("INSERT INTO audit_log VALUES (9, 'caller transaction')")
    migrate(conn)
    assert conn.execute('SELECT * FROM invoices').fetchall() == [('INV-R', 'r@example.test', '2026-10-01', 10)]
    assert conn.execute('SELECT * FROM invoice_items').fetchall() == [(8, 'INV-R', 'R', 1, 10)]
    assert conn.execute('SELECT * FROM audit_log').fetchall() == [(9, 'caller transaction')]
    assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
    conn.rollback()
elif operation == 'rollback-empty':
    conn.execute("INSERT INTO audit_log VALUES (9, 'caller transaction')")
    migrate(conn)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {'invoices', 'invoice_items', 'audit_log'}
    conn.rollback()
elif operation == 'conflict':
    conn.execute("INSERT INTO audit_log VALUES (8, 'caller work')")
    before = (conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall(),
              conn.execute('SELECT * FROM invoice_lines ORDER BY line_id').fetchall(),
              conn.execute('SELECT * FROM audit_log ORDER BY id').fetchall(),
              conn.execute('PRAGMA user_version').fetchone()[0])
    try:
        migrate(conn)
    except Exception:
        pass
    else:
        raise AssertionError('conflicting metadata accepted')
    after = (conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall(),
             conn.execute('SELECT * FROM invoice_lines ORDER BY line_id').fetchall(),
             conn.execute('SELECT * FROM audit_log ORDER BY id').fetchall(),
             conn.execute('PRAGMA user_version').fetchone()[0])
    assert after == before, 'migration changed caller transaction on conflict'
    conn.rollback()
else:
    migrate(conn)
    conn.commit()
conn.close()
raise SystemExit(42)
'''


def legacy_connection(test):
    directory = tempfile.TemporaryDirectory(prefix='rigmark-migration-')
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / 'ledger.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(LEGACY_SCHEMA)
    return conn, path


def run_candidate(test, path, operation='commit'):
    result = subprocess.run([sys.executable, '-B', '-c', CHILD, str(path), operation],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, timeout=20, check=False)
    test.assertEqual(result.returncode, 42, result.stderr[-2000:])


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


INVOICE_COLUMNS = {
    'invoice_id': ('TEXT', True, 1), 'customer_email': ('TEXT', True, 0),
    'issued_on': ('TEXT', True, 0), 'paid_cents': ('INTEGER', True, 0),
}
ITEM_COLUMNS = {
    'line_id': ('INTEGER', False, 1), 'invoice_id': ('TEXT', True, 0),
    'sku': ('TEXT', True, 0), 'quantity': ('INTEGER', True, 0),
    'unit_cents': ('INTEGER', True, 0),
}


class Acceptance(unittest.TestCase):
    def test_every_line_and_other_table_survive(self):
        conn, path = legacy_connection(self)
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
        run_candidate(self, path)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertTrue({'invoices', 'invoice_items'} <= tables(conn))
        self.assertNotIn('invoice_lines', tables(conn))
        foreign_keys = {(row[3], row[2], row[4]) for row in conn.execute(
            'PRAGMA foreign_key_list(invoice_items)')}
        self.assertEqual(foreign_keys, {('invoice_id', 'invoices', 'invoice_id')})
        require_columns(conn, 'invoices', INVOICE_COLUMNS)
        require_columns(conn, 'invoice_items', ITEM_COLUMNS)
        self.assertEqual(unrelated_state(conn), unrelated_before)
        self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 51)
        self.assertEqual(conn.execute('SELECT line_id, invoice_id, sku, quantity, unit_cents '
                                      'FROM invoice_items ORDER BY line_id').fetchall(),
                         [(r[0], r[1], r[5], r[6], r[7]) for r in sorted(rows)])
        self.assertEqual(conn.execute('SELECT invoice_id, customer_email, issued_on, paid_cents '
                                      'FROM invoices ORDER BY invoice_id').fetchall(),
                         sorted({(r[1], r[2], r[3], r[4]) for r in rows}))
        before = state(conn)
        run_candidate(self, path)
        self.assertEqual(state(conn), before)
        conn.close()

    def test_empty_legacy_schema_migrates(self):
        conn, path = legacy_connection(self)
        conn.execute("INSERT INTO audit_log VALUES (4, 'retain exactly')")
        conn.commit()
        unrelated_before = unrelated_state(conn)
        run_candidate(self, path)
        self.assertEqual(tables(conn), {'invoices', 'invoice_items', 'audit_log'})
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
        require_columns(conn, 'invoices', INVOICE_COLUMNS)
        require_columns(conn, 'invoice_items', ITEM_COLUMNS)
        self.assertEqual(unrelated_state(conn), unrelated_before)
        self.assertEqual(conn.execute('PRAGMA foreign_key_list(invoice_items)').fetchall()[0][2],
                         'invoices')
        before = state(conn)
        run_candidate(self, path)
        self.assertEqual(state(conn), before)
        conn.close()
        rollback_conn, rollback_path = legacy_connection(self)
        rollback_before = state(rollback_conn)
        run_candidate(self, rollback_path, 'rollback-empty')
        self.assertEqual(state(rollback_conn), rollback_before)
        rollback_conn.close()

    def test_conflicting_metadata_rolls_back_everything(self):
        for field, replacement in (('customer_email', 'second@example.test'),
                                   ('issued_on', '2026-10-02'),
                                   ('paid_cents', 501)):
            with self.subTest(field=field):
                conn, path = legacy_connection(self)
                first = (17, 'INV-X', 'first@example.test', '2026-10-01', 500, 'A', 1, 500)
                second = [29, 'INV-X', 'first@example.test', '2026-10-01', 500, 'B', 1, 0]
                second[{'customer_email': 2, 'issued_on': 3, 'paid_cents': 4}[field]] = replacement
                conn.executemany('INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?)',
                                 [first, tuple(second)])
                conn.execute("INSERT INTO audit_log VALUES (7, 'retain')")
                conn.commit()
                before = state(conn)
                run_candidate(self, path, 'conflict')
                self.assertEqual(state(conn), before)
                conn.close()

    def test_caller_can_roll_back_migration(self):
        conn, path = legacy_connection(self)
        before = state(conn)
        run_candidate(self, path, 'rollback')
        self.assertEqual(state(conn), before)
        conn.close()


if __name__ == '__main__':
    unittest.main()
