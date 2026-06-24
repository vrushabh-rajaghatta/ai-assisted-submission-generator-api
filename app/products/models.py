"""
Product models for managing medical device products.
"""

from sqlalchemy import Column, String, Text, Enum, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.models import BaseModel


class RegulationType(str, enum.Enum):
    """Regulation type enumeration."""
    IVD = "IVD"
    NON_IVD = "non_IVD"


class RiskClassification(str, enum.Enum):
    """Risk classification enumeration."""
    CLASS_I = "Class_I"
    CLASS_II = "Class_II"
    CLASS_III = "Class_III"
    CLASS_IV = "Class_IV"


class Product(BaseModel):
    """
    Medical device product model.
    
    Represents a medical device product within a regulatory project.
    Each product can have multiple submissions over time.
    """
    
    __tablename__ = "products"
    
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    device_type = Column(String(255), nullable=False)
    intended_use = Column(Text, nullable=False)
    regulation_type = Column(Enum(RegulationType), nullable=False, index=True)
    risk_classification = Column(Enum(RiskClassification), nullable=True, index=True)
    model_numbers = Column(JSON, nullable=True)  # Array of model numbers/variants
    manufacturer = Column(String(255), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="products")
    submissions = relationship("Submission", back_populates="product", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', type='{self.device_type}')>"