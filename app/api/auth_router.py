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
