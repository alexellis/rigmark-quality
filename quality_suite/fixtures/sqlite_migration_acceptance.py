"""Independent checks injected after the SQLite migration attempt."""
import sqlite3
import unittest

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
        conn.commit()

        migrate(conn)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertTrue({'invoices', 'invoice_items'} <= tables(conn))
        self.assertNotIn('invoice_lines', tables(conn))
        foreign_keys = {(row[3], row[2], row[4]) for row in conn.execute(
            'PRAGMA foreign_key_list(invoice_items)')}
        self.assertIn(('invoice_id', 'invoices', 'invoice_id'), foreign_keys)
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
        before = (conn.execute('SELECT * FROM invoices ORDER BY invoice_id').fetchall(),
                  conn.execute('SELECT * FROM invoice_items ORDER BY line_id').fetchall())
        migrate(conn)
        self.assertEqual(before, (
            conn.execute('SELECT * FROM invoices ORDER BY invoice_id').fetchall(),
            conn.execute('SELECT * FROM invoice_items ORDER BY line_id').fetchall()))

    def test_conflicting_metadata_rolls_back_everything(self):
        conn = legacy_connection()
        rows = [(17, 'INV-X', 'first@example.test', '2026-10-01', 500, 'A', 1, 500),
                (29, 'INV-X', 'second@example.test', '2026-10-01', 500, 'B', 1, 0)]
        conn.executemany('INSERT INTO invoice_lines VALUES (?,?,?,?,?,?,?,?)', rows)
        conn.commit()
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            migrate(conn)
        self.assertEqual(tables(conn), {'invoice_lines', 'audit_log'})
        self.assertEqual(conn.execute('SELECT * FROM invoice_lines ORDER BY line_id').fetchall(), rows)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 0)

    def test_caller_can_roll_back_migration(self):
        conn = legacy_connection()
        conn.execute("INSERT INTO invoice_lines VALUES (8, 'INV-R', 'r@example.test', '2026-10-01', 10, 'R', 1, 10)")
        migrate(conn)
        conn.rollback()
        self.assertEqual(tables(conn), {'invoice_lines', 'audit_log'})
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM invoice_lines').fetchone()[0], 0)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
