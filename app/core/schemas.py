"""
Base Pydantic schemas and common response models.
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime
from uuid import UUID
import enum


class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    
    model_config = ConfigDict(
        from_attributes=True,  # Enable ORM mode for SQLAlchemy models
        use_enum_values=True,  # Use enum values instead of enum objects
        validate_assignment=True,  # Validate on assignment
        arbitrary_types_allowed=True,  # Allow arbitrary types like UUID
    )


class TimestampSchema(BaseSchema):
    """Schema mixin for models with timestamps."""
    
    created_at: datetime
    updated_at: datetime


class UUIDSchema(BaseSchema):
    """Schema mixin for models with UUID primary keys."""
    
    id: UUID


class PaginationParams(BaseSchema):
    """Query parameters for pagination."""
    
    page: int = 1
    page_size: int = 20
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(BaseSchema):
    """Generic paginated response wrapper."""
    
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    
    @classmethod
    def create(cls, items: List[Any], total: int, pagination: PaginationParams):
        """Create a paginated response."""
        total_pages = (total + pagination.page_size - 1) // pagination.page_size
        return cls(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=total_pages
        )


class MessageResponse(BaseSchema):
    """Simple message response."""
    
    message: str
    success: bool = True


class ErrorResponse(BaseSchema):
    """Error response schema."""
    
    error: str
    detail: Optional[str] = None
    error_code: Optional[str] = None


class ValidationErrorResponse(BaseSchema):
    """Validation error response."""
    
    error: str = "Validation Error"
    detail: List[Dict[str, Any]]


# Status Enums (matching the database models)
class ProjectStatusEnum(str, enum.Enum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SubmissionStatusEnum(str, enum.Enum):
    DRAFT = "draft"
    AI_PROCESSING = "ai_processing"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    REJECTED = "rejected"


class RegulationTypeEnum(str, enum.Enum):
    IVD = "IVD"
    NON_IVD = "non_IVD"


class RiskClassificationEnum(str, enum.Enum):
    CLASS_I = "Class_I"
    CLASS_II = "Class_II"
    CLASS_III = "Class_III"
    CLASS_IV = "Class_IV"


class FileTypeEnum(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    OTHER = "other"


class ReviewStatusEnum(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ReviewableTypeEnum(str, enum.Enum):
    DOSSIER_SECTION = "dossier_section"
    SUBMISSION = "submission"
    EXTRACTED_CONTENT = "extracted_content"


class AlertSeverityEnum(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertTypeEnum(str, enum.Enum):
    MISSING_SECTION = "missing_section"
    INCOMPLETE_CONTENT = "incomplete_content"
    MISSING_FILE = "missing_file"