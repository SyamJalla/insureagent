"""Conversation domain models."""
from datetime import datetime, timezone
from typing import Literal
import uuid

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Message(BaseModel):
    message_id: str = Field(default_factory=_new_id)
    conversation_id: str
    sender: Literal["user", "assistant"]
    content: str
    escalated: bool = False
    created_at: datetime = Field(default_factory=_now)


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=_new_id)
    user_id: str
    title: str = "New conversation"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
