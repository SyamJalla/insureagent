"""Typed contracts for the LLM gateway."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ModelTier(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    REASONING = "reasoning"


class Complexity(str, Enum):
    """Written by the supervisor on every turn; consumed by the router only
    when complexity routing is enabled."""
    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


class LlmRequest(BaseModel):
    agent: str                                  # calling node name (routing + telemetry)
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    complexity: Complexity | None = None        # supervisor's score, if any
    temperature: float = 0.0


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any]


class LlmResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class CallRecord(BaseModel):
    """One line per LLM call — the unit of cost/latency observability."""
    agent: str
    model: str
    tier: ModelTier
    input_tokens: int
    output_tokens: int
    latency_ms: int
    correlation_id: str | None = None
