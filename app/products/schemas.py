"""
Product schemas for API request/response validation.
"""

from pydantic import Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from app.core.schemas import (
    BaseSchema, 
    TimestampSchema, 
    UUIDSchema, 
    RegulationTypeEnum,
    RiskClassificationEnum
)


class ProductBase(BaseSchema):
    """Base product schema with common fields."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
    device_type: str = Field(..., min_length=1, max_length=255, description="Type of medical device")
    intended_use: str = Field(..., min_length=1, description="Clinical intended use description")
    regulation_type: RegulationTypeEnum = Field(..., description="IVD or non-IVD regulation type")
    risk_classification: Optional[RiskClassificationEnum] = Field(None, description="Risk classification")
    model_numbers: Optional[List[str]] = Field(default_factory=list, description="List of model numbers/variants")
    manufacturer: Optional[str] = Field(None, max_length=255, description="Manufacturer name")


class ProductCreate(ProductBase):
    """Schema for creating a new product."""
    
    project_id: UUID = Field(..., description="ID of the parent project")


class ProductUpdate(BaseSchema):
    """Schema for updating an existing product."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    device_type: Optional[str] = Field(None, min_length=1, max_length=255)
    intended_use: Optional[str] = Field(None, min_length=1)
    regulation_type: Optional[RegulationTypeEnum] = None
    risk_classification: Optional[RiskClassificationEnum] = None
    model_numbers: Optional[List[str]] = None
    manufacturer: Optional[str] = Field(None, max_length=255)


class ProductResponse(ProductBase, UUIDSchema, TimestampSchema):
    """Schema for product API responses."""
    
    project_id: UUID
    
    # Computed fields
    submissions_count: Optional[int] = Field(None, description="Number of submissions for this product")
    latest_submission_status: Optional[str] = Field(None, description="Status of the most recent submission")
    latest_submission_date: Optional[datetime] = Field(None, description="Date of the most recent submission")


class ProductSummary(UUIDSchema):
    """Lightweight product summary for lists and references."""
    
    name: str
    device_type: str
    regulation_type: RegulationTypeEnum
    risk_classification: Optional[RiskClassificationEnum]
    created_at: datetime
    submissions_count: Optional[int] = 0


class ProductWithProject(ProductResponse):
    """Product response with project information."""
    
    project_name: str
    client_name: str


class ProductListResponse(BaseSchema):
    """Response schema for product list with optional filtering."""
    
    products: List[ProductSummary]
    total: int
    page: int
    page_size: int


class ProductStats(BaseSchema):
    """Product statistics schema."""
    
    total_products: int
    ivd_products: int
    non_ivd_products: int
    products_by_risk_class: Dict[str, int]
    products_by_device_type: List[Dict[str, Any]]


class ProductSearchFilters(BaseSchema):
    """Filters for product search."""
    
    project_id: Optional[UUID] = None
    regulation_type: Optional[RegulationTypeEnum] = None
    risk_classification: Optional[RiskClassificationEnum] = None
    device_type: Optional[str] = None
    manufacturer: Optional[str] = None
    search_term: Optional[str] = Field(None, description="Search in name, device_type, or intended_use")