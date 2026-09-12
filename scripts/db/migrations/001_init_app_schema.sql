-- 001: app-owned schema — identity + conversation state.
-- The synthetic insurance data (customers/policies/claims/...) lives in the
-- SQLite enterprise stand-in, owned by create_vectordb.py, not migrated here.

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL
        CHECK (role IN ('prospect','customer','agent','employee','admin')),
    customer_id   TEXT,          -- ID link into the enterprise DB (no cross-store FK)
    agent_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    title           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    sender          TEXT NOT NULL CHECK (sender IN ('user','assistant')),
    content         TEXT NOT NULL,
    escalated       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
