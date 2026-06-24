"""
Dossier schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal

from app.core.schemas import BaseSchema, TimestampSchema, UUIDSchema


class DossierSectionBase(BaseSchema):
    """Base dossier section schema with common fields."""
    
    section_code: str = Field(..., max_length=50, description="Section code (e.g., '1.1', '2.3.4')")
    section_title: str = Field(..., max_length=500, description="Section title")
    section_description: Optional[str] = Field(None, description="Detailed section description")
    is_required: bool = Field(default=True, description="Whether this section is required")
    order_index: int = Field(default=0, description="Order for sorting sections")
    template_source: Optional[str] = Field(None, max_length=255, description="IMDRF template source")


class DossierSectionCreate(DossierSectionBase):
    """Schema for creating a new dossier section."""
    
    submission_id: UUID = Field(..., description="ID of the parent submission")
    parent_section_id: Optional[UUID] = Field(None, description="ID of parent section for hierarchy")


class DossierSectionUpdate(BaseSchema):
    """Schema for updating an existing dossier section."""
    
    section_title: Optional[str] = Field(None, max_length=500)
    section_description: Optional[str] = None
    is_required: Optional[bool] = None
    is_completed: Optional[bool] = None
    completion_percentage: Optional[int] = Field(None, ge=0, le=100)
    order_index: Optional[int] = None


class DossierSectionResponse(DossierSectionBase, UUIDSchema, TimestampSchema):
    """Schema for dossier section API responses."""
    
    submission_id: UUID
    parent_section_id: Optional[UUID]
    is_completed: bool
    completion_percentage: int
    
    # Content fields
    content: Optional[str] = Field(None, description="User-edited section content")
    ai_extracted_content: Optional[str] = Field(None, description="AI-extracted content from files")
    ai_confidence_score: Optional[float] = Field(None, description="AI confidence score (0-1)")
    
    # Computed fields
    child_sections_count: Optional[int] = Field(None, description="Number of child sections")
    extracted_content_count: Optional[int] = Field(None, description="Number of linked extracted content items")
    reviews_count: Optional[int] = Field(None, description="Number of reviews for this section")
    missing_content_alerts: Optional[int] = Field(None, description="Number of missing content alerts")
    is_leaf: Optional[bool] = Field(None, description="True if this section has no children and can hold content")


class DossierSectionTree(DossierSectionResponse):
    """Hierarchical dossier section with children."""
    
    children: List['DossierSectionTree'] = Field(default_factory=list, description="Child sections")


# Rebuild the model to handle forward references
DossierSectionTree.model_rebuild()


class DossierSectionSummary(UUIDSchema):
    """Lightweight dossier section summary."""
    
    section_code: str
    section_title: str
    is_required: bool
    is_completed: bool
    completion_percentage: int
    child_sections_count: Optional[int] = 0


class DossierStructureResponse(BaseSchema):
    """Complete dossier structure for a submission."""
    
    submission_id: UUID
    sections: List[DossierSectionTree]
    total_sections: int
    completed_sections: int
    required_sections: int
    completed_required_sections: int
    overall_completion_percentage: float


class SectionContentMapping(BaseSchema):
    """Schema for mapping content to dossier sections."""
    
    dossier_section_id: UUID = Field(..., description="ID of the dossier section")
    extracted_content_id: UUID = Field(..., description="ID of the extracted content")
    is_primary_content: bool = Field(default=False, description="Whether this is the primary content for the section")
    relevance_score: Optional[Decimal] = Field(None, ge=0, le=1, description="Relevance score (0.00-1.00)")
    mapped_by: Optional[str] = Field(None, max_length=255, description="Who/what mapped this content")


class SectionContentMappingResponse(SectionContentMapping, UUIDSchema):
    """Response schema for section content mapping."""
    
    created_at: datetime
    
    # Related data
    section_title: Optional[str] = None
    content_type: Optional[str] = None
    content_preview: Optional[str] = Field(None, max_length=200, description="Preview of the content")


class DossierTemplate(BaseSchema):
    """Schema for IMDRF dossier templates."""
    
    template_name: str = Field(..., description="Name of the template")
    template_version: str = Field(..., description="Version of the template")
    description: Optional[str] = None
    sections: List[Dict[str, Any]] = Field(..., description="Template section structure")
    created_at: datetime
    is_active: bool = Field(default=True)


class DossierTemplateCreate(BaseSchema):
    """Schema for creating a dossier from template."""
    
    submission_id: UUID = Field(..., description="ID of the submission")
    template_name: str = Field(..., description="Name of the template to use")
    template_version: Optional[str] = Field(None, description="Specific version to use (latest if not specified)")


class DossierValidationResult(BaseSchema):
    """Schema for dossier validation results."""
    
    submission_id: UUID
    is_valid: bool
    validation_errors: List[str]
    validation_warnings: List[str]
    missing_required_sections: List[str]
    incomplete_sections: List[Dict[str, Any]]
    validation_date: datetime


class DossierExportRequest(BaseSchema):
    """Schema for dossier export requests."""
    
    submission_id: UUID = Field(..., description="ID of the submission to export")
    export_format: str = Field(default="pdf", description="Export format (pdf, docx, zip)")
    include_attachments: bool = Field(default=True, description="Whether to include file attachments")
    sections_to_include: Optional[List[UUID]] = Field(None, description="Specific sections to include (all if not specified)")


class DossierStats(BaseSchema):
    """Dossier statistics schema."""
    
    total_sections: int
    completed_sections: int
    in_progress_sections: int
    missing_sections: int
    sections_with_content: int
    sections_with_reviews: int
    average_completion_percentage: float