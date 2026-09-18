"""Typed contracts for the guardrail pipeline.

Verdict semantics: ALLOW and REDACT are non-terminal (the chain continues —
REDACT with a rewritten text); BLOCK and ESCALATE are terminal (the turn
never reaches the agent graph, the user gets `user_reply` as an in-chat
assistant message, ESCALATE additionally sets the message's escalated flag).
"""
from enum import Enum

from pydantic import BaseModel, Field


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"
    ESCALATE = "escalate"


class GuardrailVerdict(BaseModel):
    check: str
    action: GuardrailAction
    reason: str = ""
    text: str | None = None        # replacement text (normalization/redaction)
    user_reply: str | None = None  # shown to the user for BLOCK/ESCALATE
    scores: dict[str, float] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    action: GuardrailAction        # terminal outcome after mode is applied
    text: str                      # the text the rest of the request must use
    user_reply: str | None = None
    verdicts: list[GuardrailVerdict] = Field(default_factory=list)
