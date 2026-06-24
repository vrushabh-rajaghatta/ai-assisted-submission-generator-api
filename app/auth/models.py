"""Authentication models: organizations and users."""

from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.models import BaseModel


class Organization(BaseModel):
    """A customer organization. Owns users and (in stage B) all data."""

    __tablename__ = "organizations"

    name = Column(String(255), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name='{self.name}')>"


class User(BaseModel):
    """A user account belonging to an organization."""

    __tablename__ = "users"

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_super_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)

    organization = relationship("Organization", back_populates="users")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', admin={self.is_admin}, super={self.is_super_admin})>"
