ALTER TABLE conversations ADD COLUMN IF NOT EXISTS langfuse_trace_id TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS langfuse_root_observation_id TEXT;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS langfuse_trace_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS langfuse_observation_id TEXT;