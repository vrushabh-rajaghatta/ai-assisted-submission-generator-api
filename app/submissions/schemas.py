"""
Submission schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from uuid import UUID

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    SubmissionStatusEnum
)


class SubmissionBase(BaseSchema):
    """Base submission schema with common fields."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Submission name")
    submission_type: Optional[str] = Field(None, max_length=255, description="Type of submission (e.g., Medical Device License)")
    health_canada_reference: Optional[str] = Field(None, max_length=255, description="Health Canada reference number")
    target_submission_date: Optional[date] = Field(None, description="Target date for submission")


class SubmissionCreate(SubmissionBase):
    """Schema for creating a new submission."""
    
    project_id: UUID = Field(..., description="ID of the parent project")
    product_id: UUID = Field(..., description="ID of the associated product")
    created_by: Optional[str] = Field(None, max_length=255, description="User who created the submission")


class SubmissionUpdate(BaseSchema):
    """Schema for updating an existing submission."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    submission_type: Optional[str] = Field(None, max_length=255)
    status: Optional[SubmissionStatusEnum] = None
    health_canada_reference: Optional[str] = Field(None, max_length=255)
    target_submission_date: Optional[date] = None
    updated_by: Optional[str] = Field(None, max_length=255)


class SubmissionStatusUpdate(BaseSchema):
    """Schema for updating submission status with workflow validation."""
    
    status: SubmissionStatusEnum = Field(..., description="New status")
    approved_by: Optional[str] = Field(None, max_length=255, description="User approving the submission")
    notes: Optional[str] = Field(None, description="Notes about the status change")


class SubmissionResponse(SubmissionBase, UUIDSchema, TimestampSchema):
    """Schema for submission API responses."""
    
    project_id: UUID
    product_id: UUID
    status: SubmissionStatusEnum
    submitted_at: Optional[datetime]
    approved_at: Optional[datetime]
    approved_by: Optional[str]
    created_by: Optional[str]
    updated_by: Optional[str]
    
    # Computed fields (with default values)
    dossier_sections_count: Optional[int] = Field(0, description="Total number of dossier sections")
    completed_sections_count: Optional[int] = Field(0, description="Number of completed dossier sections")
    completion_percentage: Optional[float] = Field(0.0, description="Overall completion percentage")
    missing_content_alerts: Optional[int] = Field(0, description="Number of missing content alerts")
    consistency_issues: Optional[int] = Field(0, description="Number of consistency issues")


class SubmissionWithDetails(SubmissionResponse):
    """Submission response with project and product details."""
    
    project_name: str
    client_name: str
    product_name: str
    device_type: str
    regulation_type: str


class SubmissionSummary(UUIDSchema):
    """Lightweight submission summary for lists and references."""
    
    name: str
    status: SubmissionStatusEnum
    target_submission_date: Optional[date]
    completion_percentage: Optional[float]
    created_at: datetime
    product_id: UUID
    product_name: str
    project_id: UUID
    project_name: str
    submission_type: Optional[str] = None


class SubmissionListResponse(BaseSchema):
    """Response schema for submission list with optional filtering."""
    
    submissions: List[SubmissionSummary]
    total: int
    page: int
    page_size: int


class SubmissionWorkflowAction(BaseSchema):
    """Schema for submission workflow actions."""
    
    action: str = Field(..., description="Action to perform (start_ai_processing, submit_for_review, approve, reject)")
    notes: Optional[str] = Field(None, description="Notes about the action")
    performed_by: str = Field(..., description="User performing the action")


class SubmissionStats(BaseSchema):
    """Submission statistics schema."""
    
    total_submissions: int
    draft_submissions: int
    in_review_submissions: int
    approved_submissions: int
    submitted_submissions: int
    submissions_by_month: List[Dict[str, Any]]
    average_completion_time: Optional[float]  # in days


class SubmissionSearchFilters(BaseSchema):
    """Filters for submission search."""
    
    project_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    status: Optional[SubmissionStatusEnum] = None
    submission_type: Optional[str] = None
    target_date_from: Optional[date] = None
    target_date_to: Optional[date] = None
    search_term: Optional[str] = Field(None, description="Search in name or submission_type")


class SubmissionProgress(BaseSchema):
    """Schema for tracking submission progress."""
    
    submission_id: UUID
    total_sections: int
    completed_sections: int
    in_progress_sections: int
    missing_sections: int
    completion_percentage: float
    last_updated: datetime
    next_steps: List[str]