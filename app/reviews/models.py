"""
Review models for human review workflow.
"""

from sqlalchemy import Column, String, Text, Enum, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.models import BaseModel


class ReviewStatus(str, enum.Enum):
    """Review status enumeration."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ReviewableType(str, enum.Enum):
    """Types of entities that can be reviewed."""
    DOSSIER_SECTION = "dossier_section"
    SUBMISSION = "submission"
    EXTRACTED_CONTENT = "extracted_content"


class HumanReview(BaseModel):
    """
    Human review model with polymorphic relationships.
    
    Supports reviewing different types of entities:
    - Dossier sections (most common)
    - Submissions (overall approval)
    - Extracted content (AI-generated content verification)
    """
    
    __tablename__ = "human_reviews"
    
    # Polymorphic fields
    reviewable_type = Column(Enum(ReviewableType), nullable=False, index=True)
    reviewable_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Review details
    reviewer_name = Column(String(255), nullable=False)
    review_status = Column(Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False, index=True)
    review_comments = Column(Text, nullable=True)
    suggested_changes = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    
    # Specific relationships (will be populated based on reviewable_type)
    dossier_section_id = Column(UUID(as_uuid=True), ForeignKey("dossier_sections.id"), nullable=True, index=True)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True, index=True)
    extracted_content_id = Column(UUID(as_uuid=True), ForeignKey("extracted_content.id"), nullable=True, index=True)
    
    # Relationships
    dossier_section = relationship("DossierSection", back_populates="reviews")
    submission = relationship("Submission", backref="reviews")
    extracted_content = relationship("ExtractedContent", backref="reviews")
    
    def __repr__(self) -> str:
        return f"<HumanReview(id={self.id}, type='{self.reviewable_type}', status='{self.review_status}')>"
    
    @property
    def reviewable_entity(self):
        """Get the actual entity being reviewed based on reviewable_type."""
        if self.reviewable_type == ReviewableType.DOSSIER_SECTION:
            return self.dossier_section
        elif self.reviewable_type == ReviewableType.SUBMISSION:
            return self.submission
        elif self.reviewable_type == ReviewableType.EXTRACTED_CONTENT:
            return self.extracted_content
        return None