-- 003: link each assistant message to the request that produced it.
-- correlation_id lets user feedback on a message find its Langfuse trace
-- (trace id is deterministically seeded from correlation_id).
ALTER TABLE messages ADD COLUMN IF NOT EXISTS correlation_id TEXT;
