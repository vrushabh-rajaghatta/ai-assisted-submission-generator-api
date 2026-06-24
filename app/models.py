"""
Central models import module.

This module imports all SQLAlchemy models to ensure they are registered
with the Base metadata for proper table creation and relationships.
"""

# Import all models to register them with SQLAlchemy
from app.projects.models import Project
from app.products.models import Product
from app.submissions.models import Submission
from app.dossier.models import DossierSection, section_content_association
from app.files.models import UploadedFile, ExtractedContent
from app.reviews.models import HumanReview
from app.validation.models import MissingContent, ConsistencyCheck
from app.auth.models import Organization, User

# Export all models for easy importing
__all__ = [
    "Project",
    "Product", 
    "Submission",
    "DossierSection",
    "UploadedFile",
    "ExtractedContent",
    "HumanReview",
    "MissingContent",
    "ConsistencyCheck",
    "section_content_association",
    "Organization",
    "User",
]