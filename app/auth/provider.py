"""Authentication providers.

AuthProvider is the swap point: JwtAuthProvider now, a Cognito-backed
implementation later, without callers changing.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.auth.models import TokenPair, User
from app.auth.password import verify_password
from app.auth.repository import UserStore


class AuthenticationError(Exception):
    pass


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, email: str, password: str) -> TokenPair:
        """Verify credentials; return tokens. Raises AuthenticationError."""

    @abstractmethod
    def validate_token(self, token: str) -> User:
        """Resolve a bearer token to a User. Raises AuthenticationError."""


class JwtAuthProvider(AuthProvider):
    def __init__(self, users: UserStore, secret: str, algorithm: str, ttl_minutes: int):
        self._users = users
        self._secret = secret
        self._algorithm = algorithm
        self._ttl = timedelta(minutes=ttl_minutes)

    def authenticate(self, email: str, password: str) -> TokenPair:
        found = self._users.get_by_email(email)
        if not found or not verify_password(password, found[1]):
            raise AuthenticationError("invalid email or password")
        user = found[0]
        claims = {
            "sub": user.user_id,
            "role": user.role.value,
            "exp": datetime.now(timezone.utc) + self._ttl,
        }
        return TokenPair(access_token=jwt.encode(claims, self._secret, algorithm=self._algorithm))

    def validate_token(self, token: str) -> User:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError as exc:
            raise AuthenticationError("invalid or expired token") from exc
        user = self._users.get_by_id(claims["sub"])
        if user is None:
            raise AuthenticationError("unknown user")
        return user
