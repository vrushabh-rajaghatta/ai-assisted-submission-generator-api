"""Auth services: password hashing and JWT issuance."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: UUID, organization_id: UUID, is_admin: bool) -> tuple[str, int]:
    """Create a signed JWT access token. Returns (token, expires_in_seconds)."""
    expires_delta = timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "org": str(organization_id),
        "adm": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT. Returns the payload or None if invalid/expired."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
