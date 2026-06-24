"""
Simple API security helpers.
"""

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Require an API key when INTERNAL_API_KEY is configured."""
    # Keep local development friction low when no key is configured.
    if not settings.INTERNAL_API_KEY:
        return

    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
