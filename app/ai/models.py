"""
AI service data models and schemas.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from uuid import UUID


class DocumentContent(BaseModel):
    """Extracted document content."""
    
    text: str = Field(..., description="Extracted text content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    page_count: Optional[int] = Field(None, description="Number of pages")
    file_type: str = Field(..., description="Document file type")
    extraction_method: str = Field(..., description="Method used for extraction")


class SectionMapping(BaseModel):
    """AI mapping of content to dossier section."""
    
    section_id: UUID = Field(..., description="Dossier section ID")
    section_code: str = Field(..., description="Section code (e.g., '1.1')")
    section_title: str = Field(..., description="Section title")
    extracted_content: str = Field(..., description="Content mapped to this section")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="AI confidence score")
    keywords_matched: List[str] = Field(default_factory=list, description="Keywords that matched")


class AIExtractionResult(BaseModel):
    """Result of AI document processing."""
    
    document_content: DocumentContent = Field(..., description="Extracted document content")
    section_mappings: List[SectionMapping] = Field(default_factory=list, description="Content mapped to sections")
    processing_time: float = Field(..., description="Processing time in seconds")
    success: bool = Field(..., description="Whether processing was successful")
    error_message: Optional[str] = Field(None, description="Error message if processing failed")


class ContentSuggestion(BaseModel):
    """AI content suggestion for a dossier section."""
    
    section_id: UUID = Field(..., description="Target dossier section ID")
    suggested_content: str = Field(..., description="AI-suggested content")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in suggestion")
    source_files: List[str] = Field(default_factory=list, description="Source files used for suggestion")
    reasoning: str = Field(..., description="AI reasoning for the suggestion")


class AIProcessingRequest(BaseModel):
    """Request for AI processing of uploaded file."""
    
    file_id: UUID = Field(..., description="Uploaded file ID")
    submission_id: UUID = Field(..., description="Target submission ID")
    processing_options: Dict[str, Any] = Field(default_factory=dict, description="Processing options")


class AIProcessingResponse(BaseModel):
    """Response from AI processing."""
    
    file_id: UUID = Field(..., description="Processed file ID")
    submission_id: UUID = Field(..., description="Target submission ID")
    extraction_result: AIExtractionResult = Field(..., description="Extraction results")
    sections_updated: List[UUID] = Field(default_factory=list, description="Updated section IDs")
    message: str = Field(..., description="Processing status message")