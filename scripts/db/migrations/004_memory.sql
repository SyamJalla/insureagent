-- 004: memory block (docs/design/memory.md).
-- Postgres is the SOURCE OF TRUTH for memory content; the Chroma 'user_memory'
-- collection is a rebuildable similarity index over episodic rows.

CREATE TABLE IF NOT EXISTS memory_items (
    memory_id              TEXT PRIMARY KEY,
    user_id                TEXT NOT NULL REFERENCES users(user_id),
    kind                   TEXT NOT NULL CHECK (kind IN ('episodic','semantic')),
    content                TEXT NOT NULL,
    intents                TEXT[] NOT NULL DEFAULT '{}',
    actions                TEXT[] NOT NULL DEFAULT '{}',
    source_conversation_id TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at             TIMESTAMPTZ          -- NULL = no expiry (semantic facts)
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_items (user_id, kind);

-- Short-term working state (ShortTermMemory Postgres impl; Redis swap-in later)
CREATE TABLE IF NOT EXISTS conversation_scratch (
    conversation_id TEXT PRIMARY KEY,
    state           JSONB NOT NULL DEFAULT '{}',
    expires_at      TIMESTAMPTZ NOT NULL
);

-- Summarization progress marker (summarize every N new messages)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS
    summarized_message_count INTEGER NOT NULL DEFAULT 0;
