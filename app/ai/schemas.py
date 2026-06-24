"""
AI schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal

from app.core.schemas import BaseSchema, TimestampSchema, UUIDSchema


class AIExtractionRequest(BaseSchema):
    """Schema for AI content extraction requests."""
    
    file_id: UUID = Field(..., description="ID of the file to process")
    extraction_type: str = Field(default="comprehensive", description="Type of extraction to perform")
    target_sections: Optional[List[str]] = Field(None, description="Specific sections to extract content for")
    extraction_options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional extraction options")


class AIExtractionResponse(BaseSchema):
    """Schema for AI extraction responses."""
    
    extraction_id: UUID
    file_id: UUID
    status: str = Field(..., description="Status of the extraction (processing, completed, failed)")
    started_at: datetime
    completed_at: Optional[datetime]
    extracted_items_count: int
    processing_time_seconds: Optional[float]
    error_message: Optional[str]


class AIContentSuggestion(BaseSchema):
    """Schema for AI content suggestions."""
    
    suggestion_id: UUID
    content_text: str = Field(..., description="Suggested content text")
    content_type: str = Field(..., description="Type of content suggested")
    confidence_score: Decimal = Field(..., ge=0, le=1, description="AI confidence in the suggestion")
    source_context: Optional[str] = Field(None, description="Context from which this was extracted")
    suggested_section_codes: List[str] = Field(default_factory=list, description="Suggested dossier sections")
    rationale: Optional[str] = Field(None, description="AI rationale for the suggestion")


class AISectionMapping(BaseSchema):
    """Schema for AI-suggested section mappings."""
    
    extracted_content_id: UUID = Field(..., description="ID of the extracted content")
    suggested_section_id: UUID = Field(..., description="ID of the suggested dossier section")
    confidence_score: Decimal = Field(..., ge=0, le=1, description="Confidence in the mapping")
    mapping_rationale: Optional[str] = Field(None, description="Reason for the suggested mapping")
    keywords_matched: List[str] = Field(default_factory=list, description="Keywords that influenced the mapping")


class AIProcessingJob(BaseSchema):
    """Schema for AI processing jobs."""
    
    job_id: UUID
    job_type: str = Field(..., description="Type of AI processing job")
    submission_id: Optional[UUID] = Field(None, description="Associated submission ID")
    file_ids: List[UUID] = Field(default_factory=list, description="Files to process")
    status: str = Field(..., description="Job status (queued, processing, completed, failed)")
    priority: int = Field(default=5, ge=1, le=10, description="Job priority (1=highest, 10=lowest)")
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    progress_percentage: int = Field(default=0, ge=0, le=100)
    result_summary: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None


class AIProcessingJobCreate(BaseSchema):
    """Schema for creating AI processing jobs."""
    
    job_type: str = Field(..., description="Type of AI processing job")
    submission_id: Optional[UUID] = None
    file_ids: List[UUID] = Field(..., min_items=1, description="Files to process")
    priority: int = Field(default=5, ge=1, le=10)
    processing_options: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AIModelInfo(BaseSchema):
    """Schema for AI model information."""
    
    model_name: str = Field(..., description="Name of the AI model")
    model_version: str = Field(..., description="Version of the model")
    model_type: str = Field(..., description="Type of model (extraction, classification, mapping)")
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list, description="Model capabilities")
    supported_file_types: List[str] = Field(default_factory=list, description="Supported file types")
    is_active: bool = Field(default=True)
    last_updated: datetime


class AIQualityMetrics(BaseSchema):
    """Schema for AI quality metrics."""
    
    model_name: str
    accuracy_score: Optional[Decimal] = Field(None, ge=0, le=1, description="Overall accuracy score")
    precision_score: Optional[Decimal] = Field(None, ge=0, le=1, description="Precision score")
    recall_score: Optional[Decimal] = Field(None, ge=0, le=1, description="Recall score")
    f1_score: Optional[Decimal] = Field(None, ge=0, le=1, description="F1 score")
    processing_speed: Optional[float] = Field(None, description="Average processing speed (items/second)")
    error_rate: Optional[Decimal] = Field(None, ge=0, le=1, description="Error rate")
    last_evaluated: datetime
    evaluation_dataset_size: Optional[int] = None


class AIFeedback(BaseSchema):
    """Schema for AI feedback and corrections."""
    
    feedback_id: UUID
    extracted_content_id: Optional[UUID] = None
    suggestion_id: Optional[UUID] = None
    feedback_type: str = Field(..., description="Type of feedback (correction, validation, rating)")
    original_prediction: str = Field(..., description="Original AI prediction")
    corrected_value: Optional[str] = Field(None, description="Human-corrected value")
    feedback_rating: Optional[int] = Field(None, ge=1, le=5, description="Quality rating (1-5)")
    feedback_comments: Optional[str] = None
    provided_by: str = Field(..., description="User who provided feedback")
    created_at: datetime


class AIFeedbackCreate(BaseSchema):
    """Schema for creating AI feedback."""
    
    extracted_content_id: Optional[UUID] = None
    suggestion_id: Optional[UUID] = None
    feedback_type: str = Field(..., description="Type of feedback")
    original_prediction: str = Field(..., description="Original AI prediction")
    corrected_value: Optional[str] = None
    feedback_rating: Optional[int] = Field(None, ge=1, le=5)
    feedback_comments: Optional[str] = None
    provided_by: str = Field(..., description="User providing feedback")


class AITrainingData(BaseSchema):
    """Schema for AI training data management."""
    
    dataset_id: UUID
    dataset_name: str = Field(..., description="Name of the training dataset")
    dataset_type: str = Field(..., description="Type of dataset (extraction, classification, mapping)")
    description: Optional[str] = None
    sample_count: int = Field(..., ge=0, description="Number of samples in the dataset")
    created_at: datetime
    last_updated: datetime
    is_validated: bool = Field(default=False, description="Whether the dataset has been validated")
    validation_accuracy: Optional[Decimal] = Field(None, ge=0, le=1)


class AIStats(BaseSchema):
    """AI processing statistics."""
    
    total_extractions: int
    successful_extractions: int
    failed_extractions: int
    average_processing_time: float  # in seconds
    total_content_items: int
    high_confidence_items: int
    items_requiring_review: int
    feedback_submissions: int
    model_accuracy_trend: List[Dict[str, Any]]  # For charts


class AIConfigurationUpdate(BaseSchema):
    """Schema for updating AI configuration."""
    
    model_settings: Optional[Dict[str, Any]] = None
    extraction_thresholds: Optional[Dict[str, float]] = None
    processing_options: Optional[Dict[str, Any]] = None
    quality_thresholds: Optional[Dict[str, float]] = None
    updated_by: str = Field(..., description="User updating the configuration")


class AIBenchmarkResult(BaseSchema):
    """Schema for AI benchmark results."""
    
    benchmark_id: UUID
    model_name: str
    benchmark_type: str = Field(..., description="Type of benchmark test")
    test_dataset_size: int
    execution_time: float  # in seconds
    accuracy_metrics: Dict[str, float]
    performance_metrics: Dict[str, float]
    comparison_baseline: Optional[str] = None
    executed_at: datetime
    executed_by: str