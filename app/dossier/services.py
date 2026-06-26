"""
Dossier generation and management services.

This service handles the automatic generation of submission dossiers
based on IMDRF templates when submissions are created.
"""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.dossier.models import DossierSection


class LeafSectionRequiredError(Exception):
    """Raised when a write operation targets a non-leaf (parent) dossier section."""


def is_leaf_section(db: Session, section_id: uuid.UUID) -> bool:
    """A section is a leaf iff no other section lists it as parent."""
    return (
        db.query(DossierSection.id)
        .filter(DossierSection.parent_section_id == section_id)
        .first()
        is None
    )
from app.ai.content_mapper import content_mapper
from app.submissions.models import Submission
from app.core.config import settings


class DossierGenerationService:
    """Service for generating submission dossiers from IMDRF templates."""
    
    def __init__(self, db: Session):
        self.db = db
        self.templates_dir = Path(__file__).parent.parent.parent / "templates" / "imdrf"
    
    def get_template_for_submission_type(self, submission_type: str) -> Optional[Dict[str, Any]]:
        """Get the appropriate IMDRF template based on submission type."""
        # Normalize the submission type to handle variations
        normalized_type = submission_type.lower().strip() if submission_type else ""
        
        template_mapping = {
            "medical_device_license": "medical_device_license.json",
            "ivd_license": "ivd_license.json", 
            "medical_device_amendment": "medical_device_license.json",
            "ivd_amendment": "ivd_license.json",
            # Handle common variations
            "medical device license": "medical_device_license.json",
            "ivd license": "ivd_license.json",
            "in vitro diagnostic license": "ivd_license.json",
            "medical device amendment": "medical_device_license.json",
            "ivd amendment": "ivd_license.json",
            "class ii notification": "medical_device_license.json",  # Default to medical device
            "": "medical_device_license.json"  # Default for empty/null
        }
        
        template_file = template_mapping.get(normalized_type)
        if not template_file:
            return None
            
        template_path = self.templates_dir / template_file
        if not template_path.exists():
            return None
            
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def generate_dossier_for_submission(self, submission: Submission) -> List[DossierSection]:
        """Generate complete dossier structure for a submission."""
        print(f"Generating dossier for submission {submission.id} with type: '{submission.submission_type}'")
        template = self.get_template_for_submission_type(submission.submission_type)
        if not template:
            print(f"ERROR: No template found for submission type: '{submission.submission_type}'")
            print(f"Available types: {list(self.get_available_template_types())}")
            raise ValueError(f"No template found for submission type: {submission.submission_type}")
        
        print(f"Found template: {template.get('template_name')} with {len(template.get('sections', []))} sections")
        
        # Delete existing dossier sections if any (for regeneration)
        existing_sections = self.db.query(DossierSection).filter(
            DossierSection.submission_id == submission.id
        ).all()
        for section in existing_sections:
            self.db.delete(section)
        
        # Generate sections from template in two phases
        # Phase 1: Create and save parent sections
        parent_sections = []
        sections = template.get("sections", [])
        
        for section_data in sections:
            parent_section = self._create_section_from_template(
                section_data, submission.id, None
            )
            parent_sections.append(parent_section)
            self.db.add(parent_section)
        
        # Commit parent sections first to get their IDs
        self.db.commit()
        
        # Refresh to get database IDs
        for section in parent_sections:
            self.db.refresh(section)
        
        # Phase 2: Create child sections using committed parent IDs
        all_sections = parent_sections.copy()
        
        for i, section_data in enumerate(sections):
            parent_section = parent_sections[i]
            
            if "children" in section_data:
                try:
                    child_sections = self._create_child_sections(
                        section_data["children"], submission.id, parent_section.id
                    )
                    
                    # Add child sections
                    for child_section in child_sections:
                        self.db.add(child_section)
                        all_sections.append(child_section)
                    
                except Exception as e:
                    print(f"Error creating children for section {parent_section.section_code}: {e}")
        
        # Final commit for all child sections
        self.db.commit()
        
        # Refresh all sections
        for section in all_sections:
            self.db.refresh(section)
        
        return all_sections
    
    def _create_child_sections(
        self, 
        children_data: List[Dict[str, Any]], 
        submission_id: uuid.UUID, 
        parent_id: uuid.UUID
    ) -> List[DossierSection]:
        """Recursively create child sections."""
        child_sections = []
        
        for child_data in children_data:
            try:
                child_section = self._create_section_from_template(
                    child_data, submission_id, parent_id
                )
                child_sections.append(child_section)
                # Handle nested children
                if "children" in child_data:
                    nested_children = self._create_child_sections(
                        child_data["children"], submission_id, child_section.id
                    )
                    child_sections.extend(nested_children)
            except Exception as e:
                print(f"Error creating child {child_data.get('section_code', 'unknown')}: {e}")
        
        return child_sections
    
    def get_available_template_types(self):
        """Get list of available submission types."""
        return [
            "medical_device_license",
            "ivd_license", 
            "medical_device_amendment",
            "ivd_amendment"
        ]
    
    def _create_section_from_template(
        self, 
        section_data: Dict[str, Any], 
        submission_id: uuid.UUID, 
        parent_id: Optional[uuid.UUID]
    ) -> DossierSection:
        """Create a DossierSection from template data."""
        # Get content requirements for this section
        requirements = content_mapper.get_section_requirements(section_data.get("section_code", ""))
        
        # Generate placeholder content using existing method
        placeholder_content = self._generate_placeholder_content(section_data)
        
        return DossierSection(
            id=uuid.uuid4(),
            submission_id=submission_id,
            parent_section_id=parent_id,
            section_code=section_data.get("section_code", ""),
            section_title=section_data.get("section_title", ""),
            section_description=section_data.get("section_description", ""),
            is_required=section_data.get("is_required", False),
            is_completed=False,
            completion_percentage=0,
            order_index=section_data.get("order_index", 0),
            template_source="IMDRF",
            content_requirements=requirements,  # Store requirements as JSONB
            placeholder_content=placeholder_content  # Store generated placeholder
        )
    
    def _generate_placeholder_content(self, section_data: Dict[str, Any]) -> str:
        """Generate placeholder content for a section based on requirements."""
        section_title = section_data.get("section_title", "")
        section_description = section_data.get("section_description", "")
        requirements = section_data.get("content_requirements", [])
        
        placeholder = f"""# {section_title}

## Section Description
{section_description}

## Required Content

"""
        
        for i, requirement in enumerate(requirements, 1):
            placeholder += f"{i}. **{requirement}**\n   [Please provide information about {requirement.lower()}]\n\n"
        
        placeholder += """
## Instructions
- Replace the placeholder text above with actual content
- Ensure all required information is provided
- Review and validate before marking as complete

---
*This is a placeholder document generated from the IMDRF template. Please replace with actual submission content.*
"""
        
        return placeholder
    
    def regenerate_dossier(self, submission_id: uuid.UUID) -> List[DossierSection]:
        """Regenerate dossier structure for an existing submission."""
        submission = self.db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise ValueError(f"Submission not found: {submission_id}")
        
        return self.generate_dossier_for_submission(submission)
    
    def get_dossier_structure(self, submission_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get the hierarchical dossier structure for a submission."""
        sections = self.db.query(DossierSection).filter(
            DossierSection.submission_id == submission_id
        ).order_by(DossierSection.order_index).all()
        
        # Build hierarchical structure using a more robust approach
        sections_dict = {}
        root_sections = []

        # Pre-compute which section ids are parents (have at least one child)
        parent_ids = {
            str(s.parent_section_id) for s in sections if s.parent_section_id is not None
        }
        
        # First pass: Create all section data and organize by parent
        for section in sections:
            # Derive status from is_completed
            if section.is_completed:
                status = "completed"
            elif section.completion_percentage > 0:
                status = "in_progress"
            else:
                status = "not_started"
            
            section_data = {
                "id": str(section.id),
                "section_code": section.section_code,
                "section_title": section.section_title,
                "section_description": section.section_description,
                "is_required": section.is_required,
                "status": status,
                "completion_percentage": section.completion_percentage,
                "order_index": section.order_index,
                "content_requirements": section.content_requirements or [],
                "has_content": bool(section.content and section.content.strip()),
                "content": section.content,
                "ai_extracted_content": section.ai_extracted_content,
                "ai_confidence_score": section.ai_confidence_score,
                "is_leaf": str(section.id) not in parent_ids,
                "children": []
            }
            
            sections_dict[str(section.id)] = section_data
            
            if section.parent_section_id is None:
                root_sections.append(section_data)
        
        # Second pass: Build parent-child relationships
        for section in sections:
            if section.parent_section_id is not None:
                parent_id = str(section.parent_section_id)
                child_id = str(section.id)
                
                if parent_id in sections_dict:
                    parent_section = sections_dict[parent_id]
                    child_section = sections_dict[child_id]
                    parent_section["children"].append(child_section)
        
        # Sort children by order_index
        for section_data in sections_dict.values():
            section_data["children"].sort(key=lambda x: x["order_index"])
        
        return root_sections
    
    def _add_child_to_structure(self, structure: List[Dict], parent_id: str, child_data: Dict):
        """Recursively add child to the correct parent in the structure."""
        for item in structure:
            if item["id"] == parent_id:
                item["children"].append(child_data)
                return True
            elif item["children"]:
                if self._add_child_to_structure(item["children"], parent_id, child_data):
                    return True
        return False


class DossierContentService:
    """Service for managing dossier section content."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def update_section_content(
        self, 
        section_id: uuid.UUID, 
        content: str, 
        updated_by: Optional[str] = None
    ) -> DossierSection:
        """Update content for a dossier section."""
        section = self.db.query(DossierSection).filter(
            DossierSection.id == section_id
        ).first()
        
        if not section:
            raise ValueError(f"Dossier section not found: {section_id}")

        if not is_leaf_section(self.db, section_id):
            raise LeafSectionRequiredError(
                "Only leaf sections can hold content. "
                f"Section {section.section_code} has child sections — edit those instead."
            )
        
        # Update the actual content in the database
        section.content = content
        
        # Update completion status based on content presence.
        # Use AI confidence score if available (more meaningful than text length).
        # Cap at 90 — 100% is reserved for an explicit "Mark Complete" action.
        if content and content.strip():
            section.is_completed = False  # In progress
            if section.ai_confidence_score:
                section.completion_percentage = min(int(section.ai_confidence_score * 100), 90)
            else:
                # No AI score yet — content has been manually drafted
                section.completion_percentage = 50
        else:
            section.is_completed = False
            section.completion_percentage = 0
        
        self.db.commit()
        self.db.refresh(section)
        
        return section
    
    def _calculate_completion_percentage(self, content: str) -> int:
        """Retained for backward compatibility — use AI confidence score where possible."""
        if not content or not content.strip():
            return 0
        return 50  # Draft in progress; confidence score applied when AI has processed
    
    def mark_section_complete(self, section_id: uuid.UUID, completed_by: Optional[str] = None) -> DossierSection:
        """Mark a section as complete."""
        section = self.db.query(DossierSection).filter(
            DossierSection.id == section_id
        ).first()
        
        if not section:
            raise ValueError(f"Dossier section not found: {section_id}")

        if not is_leaf_section(self.db, section_id):
            raise LeafSectionRequiredError(
                "Only leaf sections can be marked complete. "
                f"Section {section.section_code} has child sections — "
                "its completion is derived from theirs."
            )
        
        section.is_completed = True
        section.completion_percentage = 100
        
        self.db.commit()
        self.db.refresh(section)
        
        return section