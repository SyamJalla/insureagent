"""FastAPI dependencies: bearer token -> User -> RequestContext."""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import RequestContext, User
from app.auth.provider import AuthenticationError, AuthProvider, JwtAuthProvider
from app.auth.repository import PostgresUserStore, UserStore
from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def get_user_store() -> UserStore:
    return PostgresUserStore(get_settings().app_db_url)


def get_auth_provider(users: UserStore = Depends(get_user_store)) -> AuthProvider:
    s = get_settings()
    return JwtAuthProvider(users, s.jwt_secret, s.jwt_algorithm, s.access_token_ttl_minutes)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthProvider = Depends(get_auth_provider),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return auth.validate_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


def get_request_context(
    user: User = Depends(get_current_user),
    users: UserStore = Depends(get_user_store),
) -> RequestContext:
    policies = (
        users.policy_numbers_for_customer(user.customer_id) if user.customer_id else []
    )
    return RequestContext(
        user=user,
        correlation_id=str(uuid.uuid4()),
        owned_policy_numbers=policies,
    )
