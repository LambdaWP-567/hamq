from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.models import LoginRequest, TokenResponse

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
_JWT_ALGORITHM = "HS256"


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.AUTH_SECRET_KEY, algorithm=_JWT_ALGORITHM)


async def get_current_user(token: str = Depends(_oauth2_scheme)) -> str:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[_JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise exc
    except JWTError:
        raise exc
    return username


async def login_for_access_token(request: LoginRequest) -> TokenResponse:
    if request.username != settings.AUTH_USERNAME or not verify_password(
        request.password, settings.AUTH_PASSWORD_HASH
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": request.username})
    return TokenResponse(access_token=token, token_type="bearer")
