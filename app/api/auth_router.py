"""Auth endpoints: login and identity."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependency import get_auth_provider, get_request_context
from app.auth.models import RequestContext, TokenPair
from app.auth.provider import AuthenticationError, AuthProvider

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginRequest, auth: AuthProvider = Depends(get_auth_provider)) -> TokenPair:
    try:
        return auth.authenticate(body.email, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


@router.get("/me")
def me(ctx: RequestContext = Depends(get_request_context)) -> dict:
    return {
        "user": ctx.user.model_dump(),
        "policy_count": len(ctx.owned_policy_numbers),
    }
