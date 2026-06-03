"""
JWT authentication module for the HAMq Controller API.

Provides:
- Password hashing/verification via passlib/bcrypt
- JWT token creation with configurable expiry
- FastAPI dependency `get_current_user` that validates the Bearer token
- `/api/auth/login` route handler
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.models import LoginRequest, TokenResponse

# ---------------------------------------------------------------------------
# Password hashing context
# ---------------------------------------------------------------------------
# bcrypt is the recommended algorithm — it's deliberately slow and includes
# a salt, making brute-force attacks expensive.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme — FastAPI will look for "Authorization: Bearer <token>"
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# JWT algorithm — HS256 is symmetric and appropriate for a single-service token
_JWT_ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against its bcrypt hash.

    Parameters
    ----------
    plain_password:
        The password as submitted by the user (never stored).
    hashed_password:
        The bcrypt hash loaded from settings / Kubernetes Secret.

    Returns
    -------
    bool
        True if the password matches, False otherwise.
    """
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Parameters
    ----------
    data:
        Claims to embed in the token payload (e.g. ``{"sub": "admin"}``).
    expires_delta:
        Custom validity period. Defaults to ``AUTH_TOKEN_EXPIRE_MINUTES``.

    Returns
    -------
    str
        A compact, URL-safe JWT string.
    """
    to_encode = data.copy()

    if expires_delta is not None:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES
        )

    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.AUTH_SECRET_KEY, algorithm=_JWT_ALGORITHM)


async def get_current_user(token: str = Depends(_oauth2_scheme)) -> str:
    """
    FastAPI dependency that validates the JWT Bearer token.

    Raises ``HTTP 401`` if the token is missing, expired, or tampered with.

    Parameters
    ----------
    token:
        Extracted automatically from the ``Authorization: Bearer …`` header.

    Returns
    -------
    str
        The ``sub`` claim (username) embedded in the token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=[_JWT_ALGORITHM],
        )
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        # Catches expired, malformed, and signature-mismatch errors
        raise credentials_exception

    return username


async def login_for_access_token(request: LoginRequest) -> TokenResponse:
    """
    Authenticate a user and return a JWT access token.

    Used as the handler for ``POST /api/auth/login``.

    Parameters
    ----------
    request:
        Username and password from the request body.

    Returns
    -------
    TokenResponse
        JWT token and token type.

    Raises
    ------
    HTTPException (401)
        If the credentials are invalid.
    """
    if request.username != settings.AUTH_USERNAME or not verify_password(
        request.password, settings.AUTH_PASSWORD_HASH
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": request.username})
    return TokenResponse(access_token=token, token_type="bearer")
