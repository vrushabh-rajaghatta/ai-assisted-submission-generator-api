"""
File schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    FileTypeEnum
)


class UploadedFileBase(BaseSchema):
    """Base uploaded file schema with common fields."""
    
    original_filename: str = Field(..., max_length=500, description="Original filename")
    file_size: int = Field(..., gt=0, description="File size in bytes")
    mime_type: str = Field(..., max_length=255, description="MIME type")
    file_type: FileTypeEnum = Field(..., description="File type category")
    upload_purpose: Optional[str] = Field(None, max_length=255, description="Purpose of the upload")


class FileUploadRequest(BaseSchema):
    """Schema for file upload requests."""
    
    project_id: UUID = Field(..., description="ID of the parent project")
    submission_id: Optional[UUID] = Field(None, description="ID of the associated submission (optional)")
    upload_purpose: Optional[str] = Field(None, max_length=255, description="Purpose of the upload")
    uploaded_by: Optional[str] = Field(None, max_length=255, description="User uploading the file")


class UploadedFileResponse(UploadedFileBase, UUIDSchema, TimestampSchema):
    """Schema for uploaded file API responses."""
    
    project_id: UUID
    submission_id: Optional[UUID]
    stored_filename: str
    file_path: str
    uploaded_by: Optional[str]
    is_processed: bool
    
    # Computed fields
    extracted_content_count: Optional[int] = Field(None, description="Number of extracted content items")
    download_url: Optional[str] = Field(None, description="URL for downloading the file")
    preview_available: Optional[bool] = Field(None, description="Whether preview is available")


class UploadedFileSummary(UUIDSchema):
    """Lightweight uploaded file summary."""
    
    original_filename: str
    file_type: FileTypeEnum
    file_size: int
    upload_purpose: Optional[str]
    is_processed: bool
    created_at: datetime
    extracted_content_count: Optional[int] = 0


class FileListResponse(BaseSchema):
    """Response schema for file list with optional filtering."""
    
    files: List[UploadedFileSummary]
    total: int
    page: int
    page_size: int


class FileProcessingRequest(BaseSchema):
    """Schema for requesting file processing."""
    
    file_id: UUID = Field(..., description="ID of the file to process")
    processing_type: str = Field(default="extract_content", description="Type of processing to perform")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Processing options")


class FileProcessingStatus(BaseSchema):
    """Schema for file processing status."""
    
    file_id: UUID
    is_processing: bool
    processing_started_at: Optional[datetime]
    processing_completed_at: Optional[datetime]
    processing_error: Optional[str]
    extracted_content_count: int
    processing_progress: Optional[int] = Field(None, ge=0, le=100, description="Processing progress percentage")


class ExtractedContentBase(BaseSchema):
    """Base extracted content schema with common fields."""
    
    content_text: str = Field(..., description="Extracted text snippet")
    content_type: Optional[str] = Field(None, max_length=255, description="Type of content extracted")
    confidence_score: Optional[Decimal] = Field(None, ge=0, le=1, description="AI confidence score (0.00-1.00)")
    page_number: Optional[int] = Field(None, gt=0, description="Source page number")
    extraction_method: Optional[str] = Field(None, max_length=255, description="Method used for extraction")


class ExtractedContentCreate(ExtractedContentBase):
    """Schema for creating extracted content."""
    
    file_id: UUID = Field(..., description="ID of the source file")


class ExtractedContentUpdate(BaseSchema):
    """Schema for updating extracted content."""
    
    content_text: Optional[str] = None
    content_type: Optional[str] = Field(None, max_length=255)
    confidence_score: Optional[Decimal] = Field(None, ge=0, le=1)
    reviewed: Optional[bool] = None


class ExtractedContentResponse(ExtractedContentBase, UUIDSchema, TimestampSchema):
    """Schema for extracted content API responses."""
    
    file_id: UUID
    reviewed: bool
    
    # Computed fields
    mapped_sections_count: Optional[int] = Field(None, description="Number of dossier sections this content is mapped to")
    reviews_count: Optional[int] = Field(None, description="Number of reviews for this content")


class ExtractedContentWithFile(ExtractedContentResponse):
    """Extracted content response with file information."""
    
    original_filename: str
    file_type: FileTypeEnum
    upload_purpose: Optional[str]


class ExtractedContentSummary(UUIDSchema):
    """Lightweight extracted content summary."""
    
    content_type: Optional[str]
    content_preview: str = Field(..., max_length=200, description="Preview of the content")
    confidence_score: Optional[Decimal]
    page_number: Optional[int]
    reviewed: bool
    created_at: datetime


class ContentExtractionStats(BaseSchema):
    """Content extraction statistics."""
    
    total_files: int
    processed_files: int
    pending_files: int
    total_extracted_items: int
    reviewed_items: int
    high_confidence_items: int
    extraction_accuracy: Optional[float]


class FileSearchFilters(BaseSchema):
    """Filters for file search."""
    
    project_id: Optional[UUID] = None
    submission_id: Optional[UUID] = None
    file_type: Optional[FileTypeEnum] = None
    upload_purpose: Optional[str] = None
    is_processed: Optional[bool] = None
    uploaded_by: Optional[str] = None
    search_term: Optional[str] = Field(None, description="Search in filename or upload_purpose")


class FileBatchOperation(BaseSchema):
    """Schema for batch file operations."""
    
    file_ids: List[UUID] = Field(..., min_items=1, description="List of file IDs")
    operation: str = Field(..., description="Operation to perform (process, delete, move)")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Operation options")


class FileBatchOperationResult(BaseSchema):
    """Result of batch file operations."""
    
    successful_operations: List[UUID]
    failed_operations: List[Dict[str, Any]]
    total_processed: int
    operation_summary: str