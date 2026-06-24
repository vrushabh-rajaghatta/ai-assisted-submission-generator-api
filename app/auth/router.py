"""Auth API: login, current user, change password, admin user management."""

import secrets
import string
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin, require_super_admin
from app.auth.models import Organization, User
from app.auth.schemas import (
    AdminPasswordResetResponse,
    ChangePasswordRequest,
    LoginRequest,
    OrganizationCreate,
    OrganizationResponse,
    SuperAdminUserCreate,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.auth.services import create_access_token, hash_password, verify_password
from app.core.database import get_db

router = APIRouter()

_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _generate_temp_password(length: int = 14) -> str:
    """Generate a URL-safe temporary password using the secrets module."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with username + password and receive a JWT."""
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token, expires_in = create_access_token(user.id, user.organization_id, user.is_admin)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()


@router.get("/admin/users", response_model=List[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: list all users in the admin's organization."""
    users = db.query(User).filter(User.organization_id == admin.organization_id).all()
    return users


@router.post("/admin/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: create a new user in the admin's organization."""
    username = payload.username
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that username already exists")

    user = User(
        organization_id=admin.organization_id,
        username=username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_admin=payload.is_admin,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/admin/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
)
async def reset_user_password(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: reset a user's password to a generated temporary value.

    The temporary password is returned once to the caller (admin) and the
    target user is forced to change it on next login. Email is not sent;
    the admin must share the temp password out-of-band.
    """
    target = db.query(User).filter(
        User.id == user_id,
        User.organization_id == admin.organization_id,
    ).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admins must reset their own password",
        )

    temp = _generate_temp_password()
    target.hashed_password = hash_password(temp)
    target.must_change_password = True
    db.commit()
    return AdminPasswordResetResponse(
        user_id=target.id,
        username=target.username,
        temporary_password=temp,
        must_change_password=True,
    )


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: deactivate a user (soft delete) in the admin's organization."""
    target = db.query(User).filter(User.id == user_id, User.organization_id == admin.organization_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself")
    target.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# Super-admin: platform-wide org and user management
# ---------------------------------------------------------------------------


@router.get("/super-admin/organizations", response_model=List[OrganizationResponse])
async def super_list_organizations(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: list every organization on the platform."""
    return db.query(Organization).order_by(Organization.name).all()


@router.post(
    "/super-admin/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def super_create_organization(
    payload: OrganizationCreate,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: create a new organization."""
    name = payload.name.strip()
    existing = db.query(Organization).filter(Organization.name == name).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An organization with that name already exists")
    org = Organization(name=name, is_active=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/super-admin/users", response_model=List[UserResponse])
async def super_list_users(
    organization_id: Optional[UUID] = Query(default=None, description="Filter by organization"),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: list every user (optionally scoped to one organization)."""
    query = db.query(User)
    if organization_id is not None:
        query = query.filter(User.organization_id == organization_id)
    return query.order_by(User.username).all()


@router.post(
    "/super-admin/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def super_create_user(
    payload: SuperAdminUserCreate,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: create a user (admin or regular) in any organization."""
    org = db.query(Organization).filter(Organization.id == payload.organization_id).first()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    username = payload.username
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that username already exists")

    user = User(
        organization_id=org.id,
        username=username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_admin=payload.is_admin,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/super-admin/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
)
async def super_reset_user_password(
    user_id: str,
    super_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: reset any user's password (any organization)."""
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == super_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /auth/change-password to change your own password",
        )

    temp = _generate_temp_password()
    target.hashed_password = hash_password(temp)
    target.must_change_password = True
    db.commit()
    return AdminPasswordResetResponse(
        user_id=target.id,
        username=target.username,
        temporary_password=temp,
        must_change_password=True,
    )


@router.delete("/super-admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def super_deactivate_user(
    user_id: str,
    super_admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Super-admin: deactivate any user on the platform."""
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == super_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself")
    target.is_active = False
    db.commit()
