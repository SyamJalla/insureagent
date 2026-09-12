-- 002: enterprise core — the insurance domain tables, moved from the SQLite
-- stand-in into Postgres. Seeded by scripts/seed_enterprise.py (deterministic
-- synthetic data, random_state=42).
--
-- Dedup decisions (do not "clean up" later without reading these):
--   * users vs customers: deliberately separate. users = who can log in
--     (any role); customers = who buys insurance. Linked by users.customer_id.
--     A customer may have no login; a prospect/CSR/admin has no customer row.
--   * agents is NEW: agent_id was previously a magic string on policies/users
--     with no table behind it. Commissions and the partner-agent persona need
--     a real entity.
--   * auto_policy_details mixes vehicle attributes with coverage terms
--     (limits/deductibles). Tranche A introduces policy_coverages; at that
--     point the coverage columns migrate there and this table shrinks to
--     vehicle attributes. Kept as-is here because the policy tools read it.

CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone         TEXT,
    date_of_birth DATE,
    state         TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','terminated')),
    joined_date DATE
);

CREATE TABLE IF NOT EXISTS policies (
    policy_number     TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL REFERENCES customers(customer_id),
    policy_type       TEXT NOT NULL CHECK (policy_type IN ('auto','home','life','health')),
    start_date        DATE NOT NULL,
    premium_amount    NUMERIC(10,2) NOT NULL,
    billing_frequency TEXT NOT NULL CHECK (billing_frequency IN ('monthly','quarterly','annual')),
    -- statuses beyond active/cancelled are pre-declared for Tranche A lifecycle work
    status            TEXT NOT NULL CHECK (status IN
        ('active','cancelled','lapsed','matured','surrendered')),
    agent_id          TEXT REFERENCES agents(agent_id)  -- NULL = direct policy
);

CREATE TABLE IF NOT EXISTS auto_policy_details (
    policy_number            TEXT PRIMARY KEY REFERENCES policies(policy_number),
    vehicle_vin              TEXT,
    vehicle_make             TEXT,
    vehicle_model            TEXT,
    vehicle_year             INTEGER,
    liability_limit          NUMERIC(12,2),
    collision_deductible     NUMERIC(10,2),
    comprehensive_deductible NUMERIC(10,2),
    uninsured_motorist       BOOLEAN,
    rental_car_coverage      BOOLEAN
);

CREATE TABLE IF NOT EXISTS billing (
    bill_id       TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL REFERENCES policies(policy_number),
    billing_date  DATE NOT NULL,
    due_date      DATE NOT NULL,
    amount_due    NUMERIC(10,2) NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('paid','pending','overdue'))
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id     TEXT PRIMARY KEY,
    bill_id        TEXT NOT NULL REFERENCES billing(bill_id),
    payment_date   DATE NOT NULL,
    amount         NUMERIC(10,2) NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('credit_card','debit_card','bank_transfer')),
    transaction_id TEXT,
    status         TEXT NOT NULL CHECK (status IN ('completed','pending','failed'))
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id       TEXT PRIMARY KEY,
    policy_number  TEXT NOT NULL REFERENCES policies(policy_number),
    claim_date     DATE NOT NULL,
    incident_type  TEXT NOT NULL CHECK (incident_type IN
        ('collision','theft','property_damage','medical','liability')),
    estimated_loss NUMERIC(12,2) NOT NULL,
    status         TEXT NOT NULL CHECK (status IN
        ('submitted','under_review','approved','paid','denied'))
);

CREATE INDEX IF NOT EXISTS idx_policies_customer ON policies (customer_id);
CREATE INDEX IF NOT EXISTS idx_policies_agent    ON policies (agent_id);
CREATE INDEX IF NOT EXISTS idx_billing_policy    ON billing (policy_number);
CREATE INDEX IF NOT EXISTS idx_payments_bill     ON payments (bill_id);
CREATE INDEX IF NOT EXISTS idx_claims_policy     ON claims (policy_number);

-- Deliberately NOT adding a users.customer_id FK: users pre-exist this
-- migration (would fail validation against the empty customers table), and
-- the seeder reloads enterprise tables wholesale. Ownership is checked in
-- code; revisit once seeding stabilizes (Tranche A).
