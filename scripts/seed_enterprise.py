"""Seed the enterprise tables in Postgres with deterministic synthetic data.

Owns the data generation formerly in utils.generate_sample_data() — moved here
so utils.py holds agents/tools/graph only. random_state=42 reproduces the same
customer/policy IDs on every machine, so demo-user links stay valid.

Full reload each run (delete + insert, FK-safe order). Requires migrations:
run scripts/db/migrate.py first (this script does it for you).

Run:  python scripts/seed_enterprise.py
"""
from datetime import datetime, timedelta
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "db"))

from migrate import apply_migrations  # noqa: E402

from app.config import get_settings  # noqa: E402

AGENTS = [
    ("AGT001", "Meera Sharma", "meera.sharma@partners.demo"),
    ("AGT002", "Arjun Patel", "arjun.patel@partners.demo"),
    ("AGT003", "Lucia Fernandez", "lucia.fernandez@partners.demo"),
]


def generate_sample_data(random_state: int = 42) -> dict[str, pd.DataFrame]:
    """Identical logic (and RNG sequence) to the retired utils version."""
    random.seed(random_state)
    np.random.seed(random_state)

    first_names = [
        "John", "Jane", "Robert", "Maria", "David", "Lisa", "Michael", "Sarah", "James", "Emily",
        "William", "Emma", "Joseph", "Olivia", "Charles", "Ava", "Thomas", "Isabella", "Daniel", "Mia",
        "Matthew", "Sophia", "Anthony", "Charlotte", "Christopher", "Amelia", "Andrew", "Harper",
        "Joshua", "Evelyn", "Ryan", "Abigail", "Brandon", "Ella", "Justin", "Scarlett", "Tyler", "Grace",
        "Alexander", "Chloe", "Kevin", "Victoria", "Jason", "Lily", "Brian", "Hannah", "Eric", "Aria",
        "Kyle", "Zoey",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
        "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
    ]

    customers = pd.DataFrame({
        "customer_id": [f"CUST{str(i).zfill(5)}" for i in range(1, 1001)],
        "first_name": [random.choice(first_names) for _ in range(1000)],
        "last_name": [random.choice(last_names) for _ in range(1000)],
        "email": [f"user{i}@example.com" for i in range(1, 1001)],
        "phone": [f"555-{str(random.randint(100, 999)).zfill(3)}-{str(random.randint(1000, 9999)).zfill(4)}" for _ in range(1000)],
        "date_of_birth": [datetime(1980, 1, 1) + timedelta(days=random.randint(0, 10000)) for _ in range(1000)],
        "state": [random.choice(["CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA"]) for _ in range(1000)],
    })

    policies = pd.DataFrame({
        "policy_number": [f"POL{str(i).zfill(6)}" for i in range(1, 1501)],
        "customer_id": [f"CUST{str(random.randint(1, 1000)).zfill(5)}" for _ in range(1500)],
        "policy_type": [random.choice(["auto", "home", "life"]) for _ in range(1500)],
        "start_date": [datetime(2023, 1, 1) + timedelta(days=random.randint(0, 365)) for _ in range(1500)],
        "premium_amount": [round(random.uniform(50, 500), 2) for _ in range(1500)],
        "billing_frequency": [random.choice(["monthly", "quarterly", "annual"]) for _ in range(1500)],
        "status": [random.choice(["active", "active", "active", "cancelled"]) for _ in range(1500)],
    })

    auto = policies[policies["policy_type"] == "auto"].copy()
    n_auto = len(auto)
    auto_policy_details = pd.DataFrame({
        "policy_number": auto["policy_number"],
        "vehicle_vin": [f"VIN{random.randint(10000000000000000, 99999999999999999)}" for _ in range(n_auto)],
        "vehicle_make": [random.choice(["Toyota", "Honda", "Ford", "Chevrolet", "Nissan"]) for _ in range(n_auto)],
        "vehicle_model": [random.choice(["Camry", "Civic", "F-150", "Malibu", "Altima"]) for _ in range(n_auto)],
        "vehicle_year": [random.randint(2015, 2023) for _ in range(n_auto)],
        "liability_limit": [random.choice([50000, 100000, 300000]) for _ in range(n_auto)],
        "collision_deductible": [random.choice([250, 500, 1000]) for _ in range(n_auto)],
        "comprehensive_deductible": [random.choice([250, 500, 1000]) for _ in range(n_auto)],
        "uninsured_motorist": [bool(random.choice([0, 1])) for _ in range(n_auto)],
        "rental_car_coverage": [bool(random.choice([0, 1])) for _ in range(n_auto)],
    })

    billing = pd.DataFrame({
        "bill_id": [f"BILL{str(i).zfill(6)}" for i in range(1, 5001)],
        "policy_number": [random.choice(policies["policy_number"]) for _ in range(5000)],
        "billing_date": [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(5000)],
        "due_date": [datetime(2024, 1, 15) + timedelta(days=random.randint(0, 90)) for _ in range(5000)],
        "amount_due": [round(random.uniform(100, 1000), 2) for _ in range(5000)],
        "status": [random.choice(["paid", "pending", "overdue"]) for _ in range(5000)],
    })

    payments = pd.DataFrame({
        "payment_id": [f"PAY{str(i).zfill(6)}" for i in range(1, 4001)],
        "bill_id": [random.choice(billing["bill_id"]) for _ in range(4000)],
        "payment_date": [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(4000)],
        "amount": [round(random.uniform(50, 500), 2) for _ in range(4000)],
        "payment_method": [random.choice(["credit_card", "debit_card", "bank_transfer"]) for _ in range(4000)],
        "transaction_id": [f"TXN{random.randint(100000, 999999)}" for _ in range(4000)],
        "status": [random.choice(["completed", "pending", "failed"]) for _ in range(4000)],
    })

    claims = pd.DataFrame({
        "claim_id": [f"CLM{str(i).zfill(6)}" for i in range(1, 301)],
        "policy_number": [random.choice(policies["policy_number"]) for _ in range(300)],
        "claim_date": [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(300)],
        "incident_type": [random.choice(["collision", "theft", "property_damage", "medical", "liability"]) for _ in range(300)],
        "estimated_loss": [round(random.uniform(500, 20000), 2) for _ in range(300)],
        "status": [random.choice(["submitted", "under_review", "approved", "paid", "denied"]) for _ in range(300)],
    })

    # Distribution channel: ~60% of policies are agent-sold, spread across the
    # partner agents; NULL = direct. Assigned here (not in seed_users) so a
    # reload of enterprise data is always self-consistent. These random calls
    # come AFTER all other generation, so earlier IDs/values are unchanged.
    agent_ids = [a[0] for a in AGENTS]
    policies["agent_id"] = [
        random.choice(agent_ids) if random.random() < 0.6 else None
        for _ in range(len(policies))
    ]

    return {
        "customers": customers,
        "policies": policies,
        "auto_policy_details": auto_policy_details,
        "billing": billing,
        "payments": payments,
        "claims": claims,
    }


def load(conn, data: dict[str, pd.DataFrame]) -> None:
    cur = conn.cursor()
    # FK-safe wipe (children first), then reload
    for table in ("claims", "payments", "billing", "auto_policy_details", "policies", "agents", "customers"):
        cur.execute(f"DELETE FROM {table}")

    cur.executemany(
        "INSERT INTO agents (agent_id, name, email, joined_date) VALUES (%s,%s,%s,%s)",
        [(a, n, e, datetime(2022, 6, 1).date()) for a, n, e in AGENTS],
    )

    for table in ("customers", "policies", "auto_policy_details", "billing", "payments", "claims"):
        df = data[table]
        cols = list(df.columns)
        rows = [tuple(r) for r in df.itertuples(index=False, name=None)]
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s",
            rows,
        )
    conn.commit()


def main() -> None:
    settings = get_settings()
    apply_migrations(settings.app_db_url)
    data = generate_sample_data(random_state=42)
    conn = psycopg2.connect(settings.app_db_url)
    load(conn, data)
    cur = conn.cursor()
    for table in ("customers", "agents", "policies", "auto_policy_details", "billing", "payments", "claims"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"{table}: {cur.fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
