"""FastAPI dependencies: bearer token -> User -> RequestContext."""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthenticatedToken, RequestContext, User
from app.auth.provider import AuthenticationError, AuthProvider, JwtAuthProvider
from app.auth.repository import PostgresUserStore, UserStore
from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def get_user_store() -> UserStore:
    return PostgresUserStore(get_settings().app_db_url)


def get_auth_provider(users: UserStore = Depends(get_user_store)) -> AuthProvider:
    s = get_settings()
    return JwtAuthProvider(users, s.jwt_secret, s.jwt_algorithm, s.access_token_ttl_minutes)


def get_authenticated_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthProvider = Depends(get_auth_provider),
) -> AuthenticatedToken:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return auth.validate_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


def get_current_user(token: AuthenticatedToken = Depends(get_authenticated_token)) -> User:
    return token.user


def get_request_context(
    token: AuthenticatedToken = Depends(get_authenticated_token),
    users: UserStore = Depends(get_user_store),
) -> RequestContext:
    user = token.user
    policies = (
        users.policy_numbers_for_customer(user.customer_id) if user.customer_id else []
    )
    return RequestContext(
        user=user,
        correlation_id=str(uuid.uuid4()),
        session_id=token.session_id,
        owned_policy_numbers=policies,
    )
