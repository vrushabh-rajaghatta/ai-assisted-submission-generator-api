"""
Validation schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    AlertSeverityEnum,
    AlertTypeEnum
)


class MissingContentBase(BaseSchema):
    """Base missing content alert schema with common fields."""
    
    alert_type: AlertTypeEnum = Field(..., description="Type of missing content alert")
    alert_message: str = Field(..., description="Description of the missing content")
    severity: AlertSeverityEnum = Field(..., description="Severity level of the alert")


class MissingContentCreate(MissingContentBase):
    """Schema for creating a missing content alert."""
    
    submission_id: UUID = Field(..., description="ID of the affected submission")
    dossier_section_id: Optional[UUID] = Field(None, description="ID of the affected dossier section")


class MissingContentUpdate(BaseSchema):
    """Schema for updating a missing content alert."""
    
    is_resolved: Optional[bool] = None
    resolution_notes: Optional[str] = Field(None, description="Notes about how the issue was resolved")


class MissingContentResponse(MissingContentBase, UUIDSchema, TimestampSchema):
    """Schema for missing content alert API responses."""
    
    submission_id: UUID
    dossier_section_id: Optional[UUID]
    is_resolved: bool
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]


class MissingContentWithContext(MissingContentResponse):
    """Missing content alert with contextual information."""
    
    submission_name: str
    project_name: str
    section_title: Optional[str]
    section_code: Optional[str]


class ConsistencyCheckBase(BaseSchema):
    """Base consistency check schema with common fields."""
    
    check_type: str = Field(..., max_length=255, description="Type of consistency check")
    description: str = Field(..., description="Description of the inconsistency found")
    affected_sections: Optional[List[UUID]] = Field(default_factory=list, description="Section IDs with inconsistent data")
    severity: AlertSeverityEnum = Field(..., description="Severity level of the inconsistency")


class ConsistencyCheckCreate(ConsistencyCheckBase):
    """Schema for creating a consistency check."""
    
    submission_id: UUID = Field(..., description="ID of the affected submission")


class ConsistencyCheckUpdate(BaseSchema):
    """Schema for updating a consistency check."""
    
    is_resolved: Optional[bool] = None
    resolution_notes: Optional[str] = Field(None, description="Notes about how the inconsistency was resolved")


class ConsistencyCheckResponse(ConsistencyCheckBase, UUIDSchema, TimestampSchema):
    """Schema for consistency check API responses."""
    
    submission_id: UUID
    is_resolved: bool
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]


class ConsistencyCheckWithContext(ConsistencyCheckResponse):
    """Consistency check with contextual information."""
    
    submission_name: str
    project_name: str
    affected_section_titles: List[str]


class ValidationRunRequest(BaseSchema):
    """Schema for requesting a validation run."""
    
    submission_id: UUID = Field(..., description="ID of the submission to validate")
    validation_types: Optional[List[str]] = Field(
        default_factory=lambda: ["missing_content", "consistency"],
        description="Types of validation to run"
    )
    force_rerun: bool = Field(default=False, description="Force rerun even if recently validated")


class ValidationRunResponse(BaseSchema):
    """Schema for validation run results."""
    
    submission_id: UUID
    validation_run_id: UUID
    started_at: datetime
    completed_at: Optional[datetime]
    status: str = Field(..., description="Status of the validation run (running, completed, failed)")
    total_checks: int
    issues_found: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int


class ValidationSummary(BaseSchema):
    """Summary of validation results for a submission."""
    
    submission_id: UUID
    last_validated_at: Optional[datetime]
    total_missing_content: int
    unresolved_missing_content: int
    total_consistency_issues: int
    unresolved_consistency_issues: int
    critical_issues: int
    validation_score: Optional[float] = Field(None, ge=0, le=100, description="Overall validation score (0-100)")
    is_submission_ready: bool = Field(..., description="Whether submission is ready based on validation")


class ValidationDashboard(BaseSchema):
    """Validation dashboard data."""
    
    project_id: Optional[UUID] = None
    total_submissions: int
    validated_submissions: int
    submissions_with_issues: int
    critical_issues_count: int
    high_issues_count: int
    medium_issues_count: int
    low_issues_count: int
    recent_validation_runs: List[ValidationRunResponse]
    top_issue_types: List[Dict[str, Any]]


class ValidationRule(BaseSchema):
    """Schema for validation rules configuration."""
    
    rule_name: str = Field(..., description="Name of the validation rule")
    rule_type: str = Field(..., description="Type of validation (missing_content, consistency, format)")
    description: str = Field(..., description="Description of what this rule validates")
    severity: AlertSeverityEnum = Field(..., description="Severity level for violations")
    is_active: bool = Field(default=True, description="Whether this rule is active")
    configuration: Dict[str, Any] = Field(default_factory=dict, description="Rule-specific configuration")


class ValidationRuleCreate(ValidationRule):
    """Schema for creating validation rules."""
    
    created_by: str = Field(..., description="User who created the rule")


class ValidationRuleUpdate(BaseSchema):
    """Schema for updating validation rules."""
    
    description: Optional[str] = None
    severity: Optional[AlertSeverityEnum] = None
    is_active: Optional[bool] = None
    configuration: Optional[Dict[str, Any]] = None
    updated_by: Optional[str] = None


class ValidationStats(BaseSchema):
    """Validation statistics schema."""
    
    total_validation_runs: int
    successful_runs: int
    failed_runs: int
    average_issues_per_submission: float
    most_common_issues: List[Dict[str, Any]]
    validation_trends: List[Dict[str, Any]]  # For charts
    resolution_rate: float  # Percentage of issues resolved


class ValidationSearchFilters(BaseSchema):
    """Filters for validation search."""
    
    submission_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    alert_type: Optional[AlertTypeEnum] = None
    severity: Optional[AlertSeverityEnum] = None
    is_resolved: Optional[bool] = None
    check_type: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search_term: Optional[str] = Field(None, description="Search in alert messages or descriptions")


class BulkValidationOperation(BaseSchema):
    """Schema for bulk validation operations."""
    
    submission_ids: List[UUID] = Field(..., min_items=1, description="List of submission IDs")
    operation: str = Field(..., description="Operation to perform (validate, resolve_issues, ignore_issues)")
    resolution_notes: Optional[str] = Field(None, description="Notes for bulk resolution")
    performed_by: str = Field(..., description="User performing the operation")


class ValidationAlert(BaseSchema):
    """Schema for validation alerts and notifications."""
    
    alert_id: UUID
    alert_type: str = Field(..., description="Type of alert (new_issues, critical_threshold, validation_failed)")
    submission_id: UUID
    project_id: UUID
    message: str = Field(..., description="Alert message")
    severity: AlertSeverityEnum
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None