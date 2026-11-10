"""Synthetic SQLite workspaces and reference implementations."""

LEGACY_SCHEMA = '''PRAGMA foreign_keys = ON;
CREATE TABLE invoice_lines (
    line_id INTEGER PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    issued_on TEXT NOT NULL,
    paid_cents INTEGER NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_cents INTEGER NOT NULL
);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, note TEXT NOT NULL);
'''

MIGRATION_STARTER = '''"""Migrate legacy invoice lines into invoices and invoice_items."""

def migrate(conn):
    rows = conn.execute("SELECT * FROM invoice_lines").fetchall()
    conn.execute("CREATE TABLE invoices (invoice_id TEXT PRIMARY KEY, customer_email TEXT NOT NULL, issued_on TEXT NOT NULL, paid_cents INTEGER NOT NULL)")
    conn.execute("CREATE TABLE invoice_items (line_id INTEGER PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id), sku TEXT NOT NULL, quantity INTEGER NOT NULL, unit_cents INTEGER NOT NULL)")
    seen = set()
    for line_id, invoice_id, email, issued_on, paid_cents, sku, quantity, unit_cents in rows:
        if invoice_id in seen:
            continue
        seen.add(invoice_id)
        conn.execute("INSERT INTO invoices VALUES (?, ?, ?, ?)",
                     (invoice_id, email, issued_on, paid_cents))
        conn.execute("INSERT INTO invoice_items VALUES (?, ?, ?, ?, ?)",
                     (line_id, invoice_id, sku, quantity, unit_cents))
    conn.execute("DROP TABLE invoice_lines")
'''

MIGRATION_REFERENCE = '''"""Preserve every invoice line in one caller-owned transaction."""

def migrate(conn):
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "invoice_lines" not in tables:
        if {"invoices", "invoice_items"} <= tables:
            return
        raise ValueError("legacy or migrated schema required")

    conn.execute("SAVEPOINT rigmark_invoice_migration")
    try:
        rows = conn.execute("SELECT line_id, invoice_id, customer_email, issued_on, "
                            "paid_cents, sku, quantity, unit_cents FROM invoice_lines "
                            "ORDER BY line_id").fetchall()
        invoices = {}
        for line_id, invoice_id, email, issued_on, paid_cents, sku, quantity, unit_cents in rows:
            metadata = (email, issued_on, paid_cents)
            if invoice_id in invoices and invoices[invoice_id] != metadata:
                raise ValueError("conflicting metadata for invoice " + invoice_id)
            invoices[invoice_id] = metadata
        conn.execute("CREATE TABLE invoices (invoice_id TEXT PRIMARY KEY, "
                     "customer_email TEXT NOT NULL, issued_on TEXT NOT NULL, "
                     "paid_cents INTEGER NOT NULL)")
        conn.execute("CREATE TABLE invoice_items (line_id INTEGER PRIMARY KEY, "
                     "invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id), "
                     "sku TEXT NOT NULL, quantity INTEGER NOT NULL, "
                     "unit_cents INTEGER NOT NULL)")
        conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?)",
                         [(invoice_id, *metadata)
                          for invoice_id, metadata in invoices.items()])
        conn.executemany("INSERT INTO invoice_items VALUES (?, ?, ?, ?, ?)",
                         [(line_id, invoice_id, sku, quantity, unit_cents)
                          for line_id, invoice_id, _, _, _, sku, quantity, unit_cents in rows])
        conn.execute("DROP TABLE invoice_lines")
        conn.execute("PRAGMA user_version = 2")
        conn.execute("RELEASE SAVEPOINT rigmark_invoice_migration")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT rigmark_invoice_migration")
        conn.execute("RELEASE SAVEPOINT rigmark_invoice_migration")
        raise
'''

MIGRATION_PUBLIC_TEST = '''import sqlite3
import unittest
from migration import migrate
from schema import LEGACY_SCHEMA

class MigrationTest(unittest.TestCase):
    def test_one_invoice(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LEGACY_SCHEMA)
        conn.execute("INSERT INTO invoice_lines VALUES (7, 'INV-7', 'a@example.test', '2026-10-01', 150, 'PEN', 2, 100)")
        migrate(conn)
        self.assertEqual(conn.execute("SELECT * FROM invoices").fetchall(),
                         [('INV-7', 'a@example.test', '2026-10-01', 150)])
        self.assertEqual(conn.execute("SELECT * FROM invoice_items").fetchall(),
                         [(7, 'INV-7', 'PEN', 2, 100)])

if __name__ == "__main__":
    unittest.main()
'''

REPORT_SCHEMA = '''"""Repeatable seed for a realistic, initially unindexed order database."""
import sqlite3

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                     status TEXT NOT NULL, ordered_on TEXT NOT NULL);
CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
                          sku TEXT NOT NULL, quantity INTEGER NOT NULL, unit_cents INTEGER NOT NULL);
"""

def seed(conn, customer_count=240, order_count=12000, salt=0):
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO customers VALUES (?, ?)",
                     ((i, f"Customer {i:04d}") for i in range(1, customer_count + 1)))
    statuses = ("pending", "cancelled", "refunded", "paid", "pending", "cancelled")
    months = ("2026-03", "2026-06", "2026-08", "2026-10")
    orders = []
    lines = []
    for i in range(1, order_count + 1):
        customer_id = ((i * 37 + salt) % customer_count) + 1
        status = statuses[(i * 17 + salt) % len(statuses)]
        month = months[(i * 19 + salt // 3) % len(months)]
        date = f"{month}-{(i % 28) + 1:02d}"
        orders.append((i, customer_id, status, date))
        lines.append((2 * i - 1, i, f"SKU-{i % 29}", i % 3 + 1, i % 97 + 50))
        lines.append((2 * i, i, f"SKU-{(i + 7) % 29}", 1, -(i % 11) if i % 13 == 0 else i % 43 + 20))
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)
    conn.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?)", lines)
    conn.commit()
'''

REPORT_STARTER = '''SELECT o.customer_id AS customer_id,
       SUM(li.quantity * li.unit_cents) AS revenue_cents
FROM orders AS o
JOIN order_lines AS li ON li.order_id = o.id
GROUP BY o.customer_id
ORDER BY revenue_cents DESC, customer_id ASC
LIMIT 10;
'''

REPORT_REFERENCE = '''SELECT o.customer_id AS customer_id,
       SUM(li.quantity * li.unit_cents) AS revenue_cents
FROM orders AS o
JOIN order_lines AS li ON li.order_id = o.id
WHERE o.status = 'paid' AND o.ordered_on >= :since
GROUP BY o.customer_id
ORDER BY revenue_cents DESC, customer_id ASC
LIMIT 10;
'''

INDEX_REFERENCE = '''CREATE INDEX orders_status_date_customer ON orders(status, ordered_on, customer_id);
CREATE INDEX order_lines_order_id ON order_lines(order_id);
'''

REPORT_PUBLIC_TEST = '''import sqlite3
import unittest
from pathlib import Path
from report_fixture import SCHEMA

class ReportTest(unittest.TestCase):
    def test_paid_recent_revenue(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?, ?)", [(1, 'One'), (2, 'Two')])
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            (1, 1, 'paid', '2026-10-02'), (2, 1, 'cancelled', '2026-10-03'),
            (3, 2, 'paid', '2026-09-30')])
        conn.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?)", [
            (1, 1, 'A', 2, 100), (2, 1, 'B', 1, -25),
            (3, 2, 'C', 1, 9999), (4, 3, 'D', 1, 400)])
        conn.executescript(Path('indexes.sql').read_text())
        rows = conn.execute(Path('report.sql').read_text(), {'since': '2026-10-01'}).fetchall()
        self.assertEqual(rows, [(1, 175)])

if __name__ == "__main__":
    unittest.main()
'''


TASK_DEFINITIONS = {
    'sqlite-migration': {
        'category': 'database', 'editable': ['migration.py', 'test_migration.py'],
        'prompt': ('Migrate the legacy invoice_lines table to invoices and '
                   'invoice_items in migration.py. Read schema.py first. '
                   'Preserve every line_id, invoice_id, customer_email, '
                   'issued_on, paid_cents, sku, quantity, and unit_cents '
                   'exactly, including multiple lines per invoice and repeated '
                   'SKUs. Set user_version to 2 and remove invoice_lines only '
                   'after a successful migration. Reject conflicting invoice '
                   'metadata without any schema or data change. A second call '
                   'must be harmless. Do not commit the caller\'s transaction. '
                   'Leave unrelated tables alone. Add regression tests in '
                   'test_migration.py and run them. Only edit those two files.'),
        'files': {'schema.py': 'LEGACY_SCHEMA = """\n' + LEGACY_SCHEMA + '"""\n',
                  'migration.py': MIGRATION_STARTER,
                  'test_migration.py': MIGRATION_PUBLIC_TEST},
    },
    'sqlite-report': {
        'category': 'database', 'editable': ['report.sql', 'indexes.sql', 'test_report.py'],
        'prompt': ('Write report.sql to return the top 10 customers by revenue '
                   'from paid orders on or after the :since date. Revenue is '
                   'the sum of quantity * unit_cents across all order lines, '
                   'including negative discount lines. Return exactly '
                   'customer_id and revenue_cents, sorted by revenue descending '
                   'then customer_id ascending. Omit customers with no qualifying '
                   'orders. The seed in report_fixture.py has many repetitive '
                   'orders and no secondary indexes. Add appropriate indexes in '
                   'indexes.sql so SQLite uses indexed lookups for both the '
                   'filtered orders and their lines; do not change the data. '
                   'Add a regression test in test_report.py and run the public '
                   'tests. Only edit report.sql, indexes.sql, and test_report.py.'),
        'files': {'report_fixture.py': REPORT_SCHEMA,
                  'report.sql': REPORT_STARTER,
                  'indexes.sql': '-- Add query indexes here.\n',
                  'test_report.py': REPORT_PUBLIC_TEST},
    },
}


def reference(task_id, workspace):
    """Install the known-good candidate for offline control checks only."""
    if task_id == 'sqlite-migration':
        (workspace / 'migration.py').write_text(MIGRATION_REFERENCE)
        with (workspace / 'test_migration.py').open('a') as tests:
            tests.write('''\nclass ReferenceMigrationTest(unittest.TestCase):
    def test_second_call(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(LEGACY_SCHEMA)
        migrate(conn)
        migrate(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
''')
    elif task_id == 'sqlite-report':
        (workspace / 'report.sql').write_text(REPORT_REFERENCE)
        (workspace / 'indexes.sql').write_text(INDEX_REFERENCE)
        with (workspace / 'test_report.py').open('a') as tests:
            tests.write('''\nclass ReferenceReportTest(unittest.TestCase):
    def test_date_boundary_and_discount(self):
        """The original report must fail this date and discount regression."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?, ?)", [(1, 'One'), (2, 'Two')])
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            (1, 1, 'paid', '2026-10-01'), (2, 2, 'paid', '2026-09-30')])
        conn.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?)", [
            (1, 1, 'A', 2, 100), (2, 1, 'discount', 1, -25), (3, 2, 'B', 1, 999)])
        conn.executescript(Path('indexes.sql').read_text())
        self.assertEqual(conn.execute(Path('report.sql').read_text(),
                         {'since': '2026-10-01'}).fetchall(), [(1, 175)])
''')
