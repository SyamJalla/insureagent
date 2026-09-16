"""Memory contracts: episodic items expire (TTL), semantic items persist;
memory is context for prompts, never authority over the database."""
from datetime import datetime, timezone
from enum import Enum
import uuid

from pydantic import BaseModel, Field


class MemoryKind(str, Enum):
    EPISODIC = "episodic"      # per-conversation summary
    SEMANTIC = "semantic"      # durable fact / preference


class MemoryItem(BaseModel):
    memory_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    kind: MemoryKind
    content: str
    intents: list[str] = []
    actions: list[str] = []
    source_conversation_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
