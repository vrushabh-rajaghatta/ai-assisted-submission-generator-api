"""
Base models and common mixins for the application.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr

from app.core.database import Base


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models."""
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UUIDMixin:
    """Mixin to add UUID primary key to models."""
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)


class BaseModel(Base, UUIDMixin, TimestampMixin):
    """Abstract base model with UUID primary key and timestamps."""
    
    __abstract__ = True


class AuditMixin:
    """Mixin to add audit fields for tracking who created/modified records."""
    
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)