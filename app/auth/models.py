"""Identity and per-request context models. Role semantics: README domain model."""
from enum import Enum

from pydantic import BaseModel


class Role(str, Enum):
    PROSPECT = "prospect"
    CUSTOMER = "customer"
    AGENT = "agent"
    EMPLOYEE = "employee"
    ADMIN = "admin"


class User(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: Role
    customer_id: str | None = None
    agent_id: str | None = None


class RequestContext(BaseModel):
    """Who is asking. Built server-side per request; never from client input.

    Flows downward only (API -> conversations -> agents -> tools).
    ID hierarchy: user_id (person) > session_id (login/JWT jti) >
    conversation_id (thread) > correlation_id (one message turn).
    """
    user: User
    correlation_id: str
    session_id: str | None = None       # JWT jti — one login session
    conversation_id: str | None = None  # stamped by ConversationService
    owned_policy_numbers: list[str] = []


class AuthenticatedToken(BaseModel):
    """Result of validating a bearer token: identity + login session."""
    user: User
    session_id: str | None = None


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
