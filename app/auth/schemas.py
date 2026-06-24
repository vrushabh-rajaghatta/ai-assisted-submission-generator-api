"""Pydantic schemas for the auth API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _normalize_username(value: str) -> str:
    """Trim whitespace and lowercase usernames so lookups are case-insensitive."""
    return value.strip().lower()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_username(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class OrganizationResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: UUID
    username: str
    full_name: Optional[str] = None
    is_admin: bool
    is_super_admin: bool = False
    is_active: bool
    must_change_password: bool = False
    organization_id: UUID
    organization: Optional[OrganizationResponse] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminPasswordResetResponse(BaseModel):
    """Returned to the admin after resetting another user's password."""
    user_id: UUID
    username: str
    temporary_password: str
    must_change_password: bool = True


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_username(value)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SuperAdminUserCreate(UserCreate):
    organization_id: UUID


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
