"""
Validation models for consistency checks and missing content alerts.
"""

from sqlalchemy import Column, String, Text, Enum, ForeignKey, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.models import BaseModel


class AlertSeverity(str, enum.Enum):
    """Alert severity enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, enum.Enum):
    """Missing content alert type enumeration."""
    MISSING_SECTION = "missing_section"
    INCOMPLETE_CONTENT = "incomplete_content"
    MISSING_FILE = "missing_file"


class MissingContent(BaseModel):
    """
    Missing content alert model.
    
    Tracks missing or incomplete content in submissions,
    helping ensure completeness before submission.
    """
    
    __tablename__ = "missing_content"
    
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True)
    dossier_section_id = Column(UUID(as_uuid=True), ForeignKey("dossier_sections.id"), nullable=True, index=True)
    alert_type = Column(Enum(AlertType), nullable=False, index=True)
    alert_message = Column(Text, nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False, index=True)
    is_resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Relationships
    submission = relationship("Submission", back_populates="missing_content_alerts")
    dossier_section = relationship("DossierSection", back_populates="missing_content_alerts")
    
    def __repr__(self) -> str:
        return f"<MissingContent(id={self.id}, type='{self.alert_type}', severity='{self.severity}')>"


class ConsistencyCheck(BaseModel):
    """
    Consistency check model.
    
    Tracks data inconsistencies across different sections or files,
    helping maintain data integrity throughout the submission.
    """
    
    __tablename__ = "consistency_checks"
    
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True)
    check_type = Column(String(255), nullable=False, index=True)  # e.g., "device_name_mismatch", "model_number_inconsistency"
    description = Column(Text, nullable=False)
    affected_sections = Column(JSON, nullable=True)  # Array of section IDs with inconsistent data
    severity = Column(Enum(AlertSeverity), nullable=False, index=True)
    is_resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationships
    submission = relationship("Submission", back_populates="consistency_checks")
    
    def __repr__(self) -> str:
        return f"<ConsistencyCheck(id={self.id}, type='{self.check_type}', severity='{self.severity}')>"