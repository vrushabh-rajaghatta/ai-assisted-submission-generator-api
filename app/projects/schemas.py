"""
Project schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    ProjectStatusEnum
)


class ProjectBase(BaseSchema):
    """Base project schema with common fields."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    client_name: str = Field(..., min_length=1, max_length=255, description="Client company name")
    client_contact_email: Optional[str] = Field(None, description="Primary contact email")
    status: ProjectStatusEnum = Field(default=ProjectStatusEnum.ACTIVE, description="Project status")
    
    @validator('client_contact_email')
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError('Invalid email format')
        return v


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""
    
    created_by: Optional[str] = Field(None, max_length=255, description="User who created the project")


class ProjectUpdate(BaseSchema):
    """Schema for updating an existing project."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    client_name: Optional[str] = Field(None, min_length=1, max_length=255)
    client_contact_email: Optional[str] = None
    status: Optional[ProjectStatusEnum] = None
    updated_by: Optional[str] = Field(None, max_length=255)
    
    @validator('client_contact_email')
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError('Invalid email format')
        return v


class ProjectResponse(ProjectBase, UUIDSchema, TimestampSchema):
    """Schema for project API responses."""
    
    created_by: Optional[str]
    updated_by: Optional[str]
    
    # Computed fields
    products_count: Optional[int] = Field(None, description="Number of products in this project")
    submissions_count: Optional[int] = Field(None, description="Number of submissions in this project")
    files_count: Optional[int] = Field(None, description="Number of files in this project")


class ProjectSummary(UUIDSchema):
    """Lightweight project summary for lists and references."""
    
    name: str
    client_name: str
    status: ProjectStatusEnum
    created_at: datetime
    products_count: Optional[int] = 0
    submissions_count: Optional[int] = 0


class ProjectListResponse(BaseSchema):
    """Response schema for project list with optional filtering."""
    
    projects: List[ProjectSummary]
    total: int
    page: int
    page_size: int
    
    
class ProjectStats(BaseSchema):
    """Project statistics schema."""
    
    total_projects: int
    active_projects: int
    completed_projects: int
    on_hold_projects: int
    cancelled_projects: int
    projects_by_month: List[dict]  # For charts/graphs