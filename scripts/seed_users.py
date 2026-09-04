"""Seed application users and policy-agent associations.

Owns ALL schema extensions beyond utils.generate_sample_data():
  - users table (identity for every role; see CONTEXT.md)
  - policies.agent_id column (NULL = direct policy)

Idempotent: safe to re-run. Never modifies utils.py-owned tables' data.
Run:  python scripts/seed_users.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.password import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

DEMO_PASSWORD = "demo123"


def pick_demo_customers(cur: sqlite3.Cursor) -> tuple[str, str]:
    """Return (customer with an active policy, customer with an open claim)."""
    active = cur.execute(
        "SELECT customer_id FROM policies WHERE status='active' ORDER BY policy_number LIMIT 1"
    ).fetchone()[0]
    claimant = cur.execute(
        """SELECT p.customer_id FROM claims c JOIN policies p USING (policy_number)
           WHERE c.status IN ('submitted','under_review') AND p.customer_id != ? LIMIT 1""",
        (active,),
    ).fetchone()[0]
    return active, claimant


def main() -> None:
    db_path = get_settings().db_path
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
               user_id       TEXT PRIMARY KEY,
               email         TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL,
               display_name  TEXT NOT NULL,
               role          TEXT NOT NULL
                   CHECK (role IN ('prospect','customer','agent','employee','admin')),
               customer_id   TEXT REFERENCES customers(customer_id),
               agent_id      TEXT,
               created_at    TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    cols = [c[1] for c in cur.execute("PRAGMA table_info(policies)")]
    if "agent_id" not in cols:
        cur.execute("ALTER TABLE policies ADD COLUMN agent_id TEXT")

    cust_active, cust_claim = pick_demo_customers(cur)

    users = [
        ("USR001", "customer1@demo.local", "Demo Customer (active policy)", "customer", cust_active, None),
        ("USR002", "customer2@demo.local", "Demo Customer (open claim)", "customer", cust_claim, None),
        ("USR003", "prospect@demo.local", "Demo Prospect", "prospect", None, None),
        ("USR004", "agent@demo.local", "Demo Agent", "agent", None, "AGT001"),
        ("USR005", "csr@demo.local", "Demo CSR", "employee", None, None),
        ("USR006", "admin@demo.local", "Demo Admin", "admin", None, None),
    ]
    pw = hash_password(DEMO_PASSWORD)
    cur.executemany(
        """INSERT OR IGNORE INTO users
           (user_id, email, password_hash, display_name, role, customer_id, agent_id)
           VALUES (?,?,?,?,?,?,?)""",
        [(uid, email, pw, name, role, cust, agt) for uid, email, name, role, cust, agt in users],
    )

    # Give the demo agent a small book of business: 5 active policies.
    cur.execute(
        """UPDATE policies SET agent_id='AGT001' WHERE policy_number IN (
               SELECT policy_number FROM policies
               WHERE status='active' AND agent_id IS NULL ORDER BY policy_number LIMIT 5)"""
    )
    conn.commit()

    for row in cur.execute(
        "SELECT user_id, email, role, customer_id, agent_id FROM users ORDER BY user_id"
    ):
        print(row)
    book = cur.execute("SELECT COUNT(*) FROM policies WHERE agent_id='AGT001'").fetchone()[0]
    print(f"AGT001 book of business: {book} policies")
    print(f"All demo passwords: {DEMO_PASSWORD}")
    conn.close()


if __name__ == "__main__":
    main()
