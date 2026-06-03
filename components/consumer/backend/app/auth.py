"""
HAMq Consumer — Authentication
================================
JWT-based authentication using python-jose and passlib.

Flow:
  1. Client POSTs username + password to /api/auth/login.
  2. We verify the password against the bcrypt hash stored in AUTH_PASSWORD_HASH.
  3. On success we issue a signed JWT with a configurable expiry window.
  4. Client includes `Authorization: Bearer <token>` on subsequent requests.
  5. Protected endpoints call `require_auth()` which validates the token.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings


# --------------------------------------------------------------------------- #
#  Password hashing
# --------------------------------------------------------------------------- #

# Use bcrypt as the hashing algorithm.  deprecated="auto" means legacy hashes
# are automatically re-hashed on next verification (transparent migration).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored *hashed* password."""
    return _pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    """Hash a plain-text password for storage.  Utility for tooling / tests."""
    return _pwd_context.hash(plain)


# --------------------------------------------------------------------------- #
#  JWT creation / validation
# --------------------------------------------------------------------------- #

_ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=True)


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Mint a new JWT for *username*.

    The token payload contains:
      - ``sub``  — subject (username)
      - ``exp``  — expiry timestamp
      - ``iat``  — issued-at timestamp
    """
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": username,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=_ALGORITHM)


def _decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.
    Raises HTTPException(401) on any failure.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=[_ALGORITHM],
        )
        if payload.get("sub") is None:
            raise credentials_error
        return payload
    except JWTError:
        raise credentials_error


# --------------------------------------------------------------------------- #
#  FastAPI dependency
# --------------------------------------------------------------------------- #

async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency that validates the Bearer token and returns the username.

    Usage::

        @router.get("/api/status")
        async def get_status(username: str = Depends(require_auth)):
            ...
    """
    payload = _decode_token(credentials.credentials)
    return payload["sub"]


# --------------------------------------------------------------------------- #
#  Login helper
# --------------------------------------------------------------------------- #

def authenticate_user(username: str, password: str) -> bool:
    """
    Verify that *username* matches AUTH_USERNAME and *password* matches
    AUTH_PASSWORD_HASH.  Returns True on success.
    """
    if username != settings.AUTH_USERNAME:
        return False
    return verify_password(password, settings.AUTH_PASSWORD_HASH)
