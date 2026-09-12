"""Typed contracts for the tool layer. No raw dicts cross this boundary."""
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.auth.models import RequestContext, Role


class ToolSpec(BaseModel):
    """Registry entry: schema (source of truth for the LLM) + access policy."""
    name: str
    description: str
    parameters: dict[str, Any]                  # JSON schema, incl. "required"
    allowed_roles: set[Role]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolResult(BaseModel):
    tool: str
    ok: bool = True
    data: Any = None
    error: str | None = None


class ToolDenied(Exception):
    """Raised when RBAC or validation rejects a call. Message is safe to show
    the LLM (it should adjust), never leaks data."""


# A tool implementation: (ctx, **validated_args) -> data.
# ctx comes from the gateway (server-resolved identity), NEVER from the LLM.
ToolFunc = Callable[..., Any]


class RegisteredTool(BaseModel):
    spec: ToolSpec
    func: ToolFunc

    model_config = {"arbitrary_types_allowed": True}
