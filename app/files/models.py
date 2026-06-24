"""
File models for handling uploads and storage.
"""

from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey, Enum, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.models import BaseModel, AuditMixin


class FileType(str, enum.Enum):
    """File type enumeration."""
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    OTHER = "other"


class UploadedFile(BaseModel, AuditMixin):
    """
    Uploaded file model.
    
    Stores metadata for files uploaded to the system.
    Files can be associated with projects (general files) or submissions (specific files).
    """
    
    __tablename__ = "uploaded_files"
    
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    submission_id = Column(UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True, index=True)  # Optional - files can be project-level
    original_filename = Column(String(500), nullable=False)
    stored_filename = Column(String(500), nullable=False, unique=True)  # UUID-based filename
    file_path = Column(String(1000), nullable=False)  # Full path to stored file
    file_size = Column(BigInteger, nullable=False)  # Size in bytes
    mime_type = Column(String(255), nullable=False)
    file_type = Column(Enum(FileType), nullable=False, index=True)
    file_hash = Column(String(64), nullable=False)  # SHA-256 hash for integrity checking
    upload_purpose = Column(String(255), nullable=True)  # e.g., "product_specification", "clinical_data"
    uploaded_by = Column(String(255), nullable=True)
    is_processed = Column(Boolean, default=False, nullable=False, index=True)  # Has AI processed this file?
    
    # Relationships
    project = relationship("Project", back_populates="files")
    submission = relationship("Submission", backref="files")  # Optional relationship
    extracted_contents = relationship("ExtractedContent", back_populates="file", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<UploadedFile(id={self.id}, filename='{self.original_filename}', type='{self.file_type}')>"


class ExtractedContent(BaseModel):
    """
    Content extracted from uploaded files.
    
    Stores text snippets and metadata extracted from files,
    typically by AI processing services.
    """
    
    __tablename__ = "extracted_content"
    
    file_id = Column(UUID(as_uuid=True), ForeignKey("uploaded_files.id"), nullable=False, index=True)
    content_text = Column(String, nullable=False)  # Extracted text snippet (using String for unlimited length in PostgreSQL)
    content_type = Column(String(255), nullable=True)  # e.g., "device_description", "intended_use", "specifications"
    confidence_score = Column(Numeric(precision=3, scale=2), nullable=True)  # AI confidence 0.00-1.00
    page_number = Column(Integer, nullable=True)  # Source page in document
    extraction_method = Column(String(255), nullable=True)  # e.g., "mock_ai", "gpt4", "manual"
    reviewed = Column(Boolean, default=False, nullable=False, index=True)
    
    # Relationships
    file = relationship("UploadedFile", back_populates="extracted_contents")
    
    # Many-to-many relationship with dossier sections
    dossier_sections = relationship(
        "DossierSection",
        secondary="section_content_map",
        back_populates="extracted_contents"
    )
    
    def __repr__(self) -> str:
        return f"<ExtractedContent(id={self.id}, type='{self.content_type}', confidence={self.confidence_score})>"