"""Auth endpoints: login and identity."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependency import get_auth_provider, get_request_context
from app.auth.models import RequestContext, TokenPair
from app.auth.provider import AuthenticationError, AuthProvider

router = APIRouter(tags=["auth"])
logger = logging.getLogger("insureagent.auth")


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginRequest, auth: AuthProvider = Depends(get_auth_provider)) -> TokenPair:
    try:
        tokens = auth.authenticate(body.email, body.password)
    except AuthenticationError as exc:
        # The production metric-filter feed: alarm on spikes of these.
        logger.warning("🔐 login FAILED | email=%s", body.email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    logger.info("🔐 login ok | email=%s", body.email)
    return tokens


@router.get("/me")
def me(ctx: RequestContext = Depends(get_request_context)) -> dict:
    return {
        "user": ctx.user.model_dump(),
        "policy_count": len(ctx.owned_policy_numbers),
    }


# --- Memory controls (policy: user can always view and hard-delete) ---------

@router.get("/me/memory")
def my_memory(ctx: RequestContext = Depends(get_request_context)) -> list[dict]:
    from app.memory.store import get_memory_store

    return [m.model_dump() for m in get_memory_store().list_for_user(ctx.user.user_id)]


@router.delete("/me/memory", status_code=status.HTTP_200_OK)
def clear_my_memory(ctx: RequestContext = Depends(get_request_context)) -> dict:
    from app.memory.store import get_memory_store

    removed = get_memory_store().delete(ctx.user.user_id)
    logger.info("🧠 memory cleared | user=%s removed=%d", ctx.user.user_id, removed)
    return {"removed": removed}


@router.delete("/me/memory/{memory_id}", status_code=status.HTTP_200_OK)
def delete_memory_item(
    memory_id: str, ctx: RequestContext = Depends(get_request_context)
) -> dict:
    from app.memory.store import get_memory_store

    removed = get_memory_store().delete(ctx.user.user_id, memory_id)
    if removed == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory item not found")
    return {"removed": removed}
