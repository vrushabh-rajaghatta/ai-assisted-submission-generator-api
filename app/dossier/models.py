"""
Dossier models for IMDRF template structure and section management.
"""

from sqlalchemy import Column, String, Text, Boolean, Integer, ForeignKey, Table, Numeric, DateTime, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.models import BaseModel


# Association table for many-to-many relationship between dossier sections and extracted content
section_content_association = Table(
    'section_content_map',
    BaseModel.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column('dossier_section_id', UUID(as_uuid=True), ForeignKey('dossier_sections.id'), nullable=False),
    Column('extracted_content_id', UUID(as_uuid=True), ForeignKey('extracted_content.id'), nullable=False),
    Column('is_primary_content', Boolean, default=False, nullable=False),
    Column('relevance_score', Numeric(precision=3, scale=2), nullable=True),
    Column('mapped_by', String(255), nullable=True),
    Column('created_at', DateTime, default=datetime.utcnow, nullable=False),
    extend_existing=True
)


class DossierSection(BaseModel):
    """
    IMDRF dossier section model.
    
    Represents hierarchical sections in an IMDRF template structure.
    Supports parent-child relationships for nested sections.
    """
    
    __tablename__ = "dossier_sections"
    
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True)
    parent_section_id = Column(UUID(as_uuid=True), ForeignKey("dossier_sections.id"), nullable=True, index=True)
    section_code = Column(String(50), nullable=False, index=True)  # e.g., "1.1", "2.3.4"
    section_title = Column(String(500), nullable=False)
    section_description = Column(Text, nullable=True)
    is_required = Column(Boolean, default=True, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False, index=True)
    completion_percentage = Column(Integer, default=0, nullable=False)  # 0-100
    order_index = Column(Integer, nullable=False, default=0)  # For sorting sections
    template_source = Column(String(255), nullable=True)  # Which IMDRF template this came from
    
    # Content fields for AI processing
    content = Column(Text, nullable=True)  # User-edited section content
    content_requirements = Column(JSONB, nullable=True)  # Requirements from IMDRF template
    placeholder_content = Column(Text, nullable=True)  # Generated placeholder text
    ai_extracted_content = Column(Text, nullable=True)  # AI-extracted content from files
    ai_confidence_score = Column(Float, nullable=True)  # AI confidence in extraction (0-1)
    
    # Conflict tracking fields
    has_conflicts = Column(Boolean, default=False, nullable=False, index=True)  # Flag for conflicting data
    conflict_sources = Column(JSONB, nullable=True)  # Array of conflicting content from different files
    source_file_id = Column(UUID(as_uuid=True), ForeignKey("uploaded_files.id"), nullable=True)  # Primary source file
    
    # Relationships
    submission = relationship("Submission", back_populates="dossier_sections")
    parent_section = relationship("DossierSection", remote_side="DossierSection.id", backref="child_sections")
    reviews = relationship("HumanReview", back_populates="dossier_section", cascade="all, delete-orphan")
    missing_content_alerts = relationship("MissingContent", back_populates="dossier_section", cascade="all, delete-orphan")
    
    # Many-to-many relationship with extracted content
    extracted_contents = relationship(
        "ExtractedContent",
        secondary=section_content_association,
        back_populates="dossier_sections"
    )
    
    def __repr__(self) -> str:
        return f"<DossierSection(id={self.id}, code='{self.section_code}', title='{self.section_title}')>"