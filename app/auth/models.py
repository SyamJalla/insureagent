"""Identity and per-request context models. See CONTEXT.md for role semantics."""
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

    Flows downward only (API -> conversations -> agents -> tools). The future
    tool-layer authorization reads this object.
    """
    user: User
    correlation_id: str
    owned_policy_numbers: list[str] = []


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
