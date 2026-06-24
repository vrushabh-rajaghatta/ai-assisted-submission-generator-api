"""
Submission models for managing regulatory submissions.
"""

from sqlalchemy import Column, String, Enum, ForeignKey, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.models import BaseModel, AuditMixin


class SubmissionStatus(str, enum.Enum):
    """Submission status enumeration."""
    DRAFT = "draft"
    AI_PROCESSING = "ai_processing"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"


class Submission(BaseModel, AuditMixin):
    """
    Regulatory submission model.
    
    Represents a regulatory submission for a specific product,
    tracking the submission lifecycle and approval process.
    """
    
    __tablename__ = "submissions"
    
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    submission_type = Column(String(255), nullable=True)  # e.g., "Medical Device License", "Amendment"
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.DRAFT, nullable=False, index=True)
    health_canada_reference = Column(String(255), nullable=True, index=True)
    target_submission_date = Column(Date, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)
    
    # Relationships
    organization = relationship("app.auth.models.Organization")
    project = relationship("app.projects.models.Project", back_populates="submissions")
    product = relationship("app.products.models.Product", back_populates="submissions")
    dossier_sections = relationship("app.dossier.models.DossierSection", back_populates="submission", cascade="all, delete-orphan")
    missing_content_alerts = relationship("app.validation.models.MissingContent", back_populates="submission", cascade="all, delete-orphan")
    consistency_checks = relationship("app.validation.models.ConsistencyCheck", back_populates="submission", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Submission(id={self.id}, name='{self.name}', status='{self.status}')>"