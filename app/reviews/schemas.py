"""
Review schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    ReviewStatusEnum,
    ReviewableTypeEnum
)


class HumanReviewBase(BaseSchema):
    """Base human review schema with common fields."""
    
    reviewer_name: str = Field(..., max_length=255, description="Name of the reviewer")
    review_comments: Optional[str] = Field(None, description="Review comments")
    suggested_changes: Optional[str] = Field(None, description="Suggested changes or improvements")


class HumanReviewCreate(HumanReviewBase):
    """Schema for creating a new review."""
    
    reviewable_type: ReviewableTypeEnum = Field(..., description="Type of entity being reviewed")
    reviewable_id: UUID = Field(..., description="ID of the entity being reviewed")
    review_status: ReviewStatusEnum = Field(default=ReviewStatusEnum.PENDING, description="Review status")


class HumanReviewUpdate(BaseSchema):
    """Schema for updating an existing review."""
    
    review_status: Optional[ReviewStatusEnum] = None
    review_comments: Optional[str] = None
    suggested_changes: Optional[str] = None
    reviewer_name: Optional[str] = Field(None, max_length=255)


class ReviewSubmission(BaseSchema):
    """Schema for submitting a review decision."""
    
    review_status: ReviewStatusEnum = Field(..., description="Final review decision")
    review_comments: Optional[str] = Field(None, description="Review comments")
    suggested_changes: Optional[str] = Field(None, description="Suggested changes if rejected or needs changes")


class HumanReviewResponse(HumanReviewBase, UUIDSchema, TimestampSchema):
    """Schema for human review API responses."""
    
    reviewable_type: ReviewableTypeEnum
    reviewable_id: UUID
    review_status: ReviewStatusEnum
    reviewed_at: Optional[datetime]
    
    # Specific relationship IDs (based on reviewable_type)
    dossier_section_id: Optional[UUID]
    submission_id: Optional[UUID]
    extracted_content_id: Optional[UUID]


class HumanReviewWithContext(HumanReviewResponse):
    """Review response with contextual information about the reviewed entity."""
    
    # Context based on reviewable_type
    entity_title: Optional[str] = Field(None, description="Title/name of the reviewed entity")
    entity_description: Optional[str] = Field(None, description="Description of the reviewed entity")
    project_name: Optional[str] = Field(None, description="Associated project name")
    submission_name: Optional[str] = Field(None, description="Associated submission name")


class HumanReviewSummary(UUIDSchema):
    """Lightweight review summary."""
    
    reviewable_type: ReviewableTypeEnum
    review_status: ReviewStatusEnum
    reviewer_name: str
    reviewed_at: Optional[datetime]
    created_at: datetime
    entity_title: Optional[str]


class ReviewListResponse(BaseSchema):
    """Response schema for review list with optional filtering."""
    
    reviews: List[HumanReviewSummary]
    total: int
    page: int
    page_size: int


class ReviewWorkflowAction(BaseSchema):
    """Schema for review workflow actions."""
    
    action: str = Field(..., description="Action to perform (assign, reassign, escalate, close)")
    assignee: Optional[str] = Field(None, description="User to assign the review to")
    notes: Optional[str] = Field(None, description="Notes about the action")
    priority: Optional[str] = Field(None, description="Priority level (low, medium, high, urgent)")


class ReviewAssignment(BaseSchema):
    """Schema for review assignments."""
    
    reviewable_type: ReviewableTypeEnum = Field(..., description="Type of entity to review")
    reviewable_id: UUID = Field(..., description="ID of the entity to review")
    assigned_to: str = Field(..., max_length=255, description="User assigned to review")
    assigned_by: str = Field(..., max_length=255, description="User making the assignment")
    due_date: Optional[datetime] = Field(None, description="Due date for the review")
    priority: Optional[str] = Field(None, description="Priority level")
    instructions: Optional[str] = Field(None, description="Special instructions for the reviewer")


class ReviewBatch(BaseSchema):
    """Schema for batch review operations."""
    
    review_ids: List[UUID] = Field(..., min_items=1, description="List of review IDs")
    action: str = Field(..., description="Batch action (approve_all, reject_all, reassign)")
    reviewer_name: Optional[str] = Field(None, description="Reviewer for batch operations")
    comments: Optional[str] = Field(None, description="Batch comments")


class ReviewStats(BaseSchema):
    """Review statistics schema."""
    
    total_reviews: int
    pending_reviews: int
    approved_reviews: int
    rejected_reviews: int
    needs_changes_reviews: int
    reviews_by_reviewer: Dict[str, int]
    average_review_time: Optional[float]  # in hours
    reviews_by_entity_type: Dict[str, int]
    overdue_reviews: int


class ReviewSearchFilters(BaseSchema):
    """Filters for review search."""
    
    reviewable_type: Optional[ReviewableTypeEnum] = None
    review_status: Optional[ReviewStatusEnum] = None
    reviewer_name: Optional[str] = None
    project_id: Optional[UUID] = None
    submission_id: Optional[UUID] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search_term: Optional[str] = Field(None, description="Search in comments or entity titles")


class ReviewNotification(BaseSchema):
    """Schema for review notifications."""
    
    review_id: UUID
    notification_type: str = Field(..., description="Type of notification (assigned, overdue, completed)")
    recipient: str = Field(..., description="User to notify")
    message: str = Field(..., description="Notification message")
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None


class ReviewTemplate(BaseSchema):
    """Schema for review templates and checklists."""
    
    template_name: str = Field(..., description="Name of the review template")
    reviewable_type: ReviewableTypeEnum = Field(..., description="Type of entity this template applies to")
    checklist_items: List[str] = Field(..., description="List of items to check during review")
    required_fields: List[str] = Field(default_factory=list, description="Required fields for this review type")
    instructions: Optional[str] = Field(None, description="Instructions for reviewers")
    is_active: bool = Field(default=True)