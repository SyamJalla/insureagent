"""Seed demo users and the demo agent's book of business — all in Postgres.

Requires migrations + enterprise seed first (both applied automatically).
Idempotent: safe to re-run.

Run:  python scripts/seed_users.py
"""
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "db"))

from migrate import apply_migrations  # noqa: E402

from app.auth.password import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

DEMO_PASSWORD = "demo123"


def pick_demo_customers(cur) -> tuple[str, str, str, str]:
    """Deterministic picks: (active policy, open claim, multi-policy,
    cancelled+active) — one interesting customer per demo persona."""
    cur.execute("SELECT COUNT(*) FROM policies")
    if cur.fetchone()[0] == 0:
        raise SystemExit(
            "The policies table is empty — run `python scripts/seed_enterprise.py` "
            "first (it must finish and print row counts), then re-run this script."
        )
    cur.execute(
        "SELECT customer_id FROM policies WHERE status='active' ORDER BY policy_number LIMIT 1"
    )
    active = cur.fetchone()[0]
    # Open claim AND the richest claim history — a better demo story, and a
    # deterministic pick with a clear margin (golden cases 7/11 pin this
    # customer's policy facts, so the pick must converge on every machine;
    # ON CONFLICT DO NOTHING means a changed pick only applies to fresh
    # setups — hence the strong ordering).
    cur.execute(
        """SELECT p.customer_id FROM claims c JOIN policies p USING (policy_number)
           WHERE p.customer_id != %s
           GROUP BY p.customer_id
           HAVING bool_or(c.status IN ('submitted','under_review'))
           ORDER BY COUNT(*) DESC, p.customer_id LIMIT 1""",
        (active,),
    )
    claimant = cur.fetchone()[0]
    cur.execute(
        """SELECT customer_id FROM policies WHERE customer_id NOT IN (%s, %s)
           GROUP BY customer_id
           ORDER BY COUNT(*) DESC, COUNT(DISTINCT policy_type) DESC, customer_id
           LIMIT 1 OFFSET 1""",  # offset 1 -> 6 policies across 3 types
        (active, claimant),
    )
    multi = cur.fetchone()[0]
    cur.execute(
        """SELECT customer_id FROM policies WHERE customer_id NOT IN (%s, %s, %s)
           GROUP BY customer_id
           HAVING bool_or(status='cancelled') AND bool_or(status='active')
           ORDER BY customer_id LIMIT 1""",
        (active, claimant, multi),
    )
    cancelled = cur.fetchone()[0]
    cur.execute(
        """SELECT p.customer_id FROM billing b JOIN policies p USING (policy_number)
           WHERE b.status = 'overdue' AND p.customer_id NOT IN (%s, %s, %s, %s)
           GROUP BY p.customer_id
           ORDER BY COUNT(*) DESC, p.customer_id LIMIT 1""",
        (active, claimant, multi, cancelled),
    )
    overdue = cur.fetchone()[0]
    return active, claimant, multi, cancelled, overdue


def main() -> None:
    settings = get_settings()
    apply_migrations(settings.app_db_url)

    conn = psycopg2.connect(settings.app_db_url)
    cur = conn.cursor()

    cust_active, cust_claim, cust_multi, cust_cancelled, cust_overdue = pick_demo_customers(cur)

    users = [
        ("USR001", "customer1@demo.local", "Demo Customer (active policy)", "customer", cust_active, None),
        ("USR002", "customer2@demo.local", "Demo Customer (open claim)", "customer", cust_claim, None),
        ("USR003", "prospect@demo.local", "Demo Prospect", "prospect", None, None),
        ("USR004", "agent@demo.local", "Demo Agent", "agent", None, "AGT001"),
        ("USR005", "csr@demo.local", "Demo CSR", "employee", None, None),
        ("USR006", "admin@demo.local", "Demo Admin", "admin", None, None),
        ("USR007", "customer3@demo.local", "Demo Customer (multi-policy)", "customer", cust_multi, None),
        ("USR008", "customer4@demo.local", "Demo Customer (cancelled policy)", "customer", cust_cancelled, None),
        ("USR009", "customer5@demo.local", "Demo Customer (overdue bills)", "customer", cust_overdue, None),
    ]
    pw = hash_password(DEMO_PASSWORD)
    cur.executemany(
        """INSERT INTO users
           (user_id, email, password_hash, display_name, role, customer_id, agent_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
        [(uid, email, pw, name, role, cust, agt) for uid, email, name, role, cust, agt in users],
    )

    # Book of business is assigned by seed_enterprise.py (part of the data,
    # not demo setup) — nothing to do here beyond linking the login.
    conn.commit()

    cur.execute("SELECT user_id, email, role, customer_id, agent_id FROM users ORDER BY user_id")
    for row in cur.fetchall():
        print(row)
    cur.execute("SELECT COUNT(*) FROM policies WHERE agent_id = %s", ("AGT001",))
    print(f"AGT001 book of business: {cur.fetchone()[0]} policies")
    print(f"All demo passwords: {DEMO_PASSWORD}")
    conn.close()


if __name__ == "__main__":
    main()
