"""
Dossier API router for IMDRF template management and section operations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import func, and_, or_
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.dossier.models import DossierSection
from app.submissions.models import Submission
from app.dossier.services import DossierGenerationService, DossierContentService
from app.dossier.schemas import (
    DossierSectionCreate,
    DossierSectionUpdate,
    DossierSectionResponse,
    DossierSectionTree,
    DossierSectionSummary,
    DossierStructureResponse,
    SectionContentMapping,
    SectionContentMappingResponse,
    DossierTemplate,
    DossierTemplateCreate,
    DossierValidationResult,
    DossierExportRequest,
    DossierStats
)
from app.core.schemas import PaginationParams, PaginatedResponse, MessageResponse

router = APIRouter()


def _assert_submission_in_org(submission_id: UUID, db: Session, current_user: User) -> Submission:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission or (
        not current_user.is_super_admin
        and submission.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    return submission


def _get_scoped_section(
    section_id: UUID, db: Session, current_user: User, *, options=None
) -> DossierSection:
    q = db.query(DossierSection)
    if options:
        q = q.options(*options)
    section = q.filter(DossierSection.id == section_id).first()
    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier section not found",
        )
    if not current_user.is_super_admin:
        submission = db.query(Submission).filter(
            Submission.id == section.submission_id
        ).first()
        if not submission or submission.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dossier section not found",
            )
    return section


@router.post("/sections", response_model=DossierSectionResponse, status_code=status.HTTP_201_CREATED)
async def create_dossier_section(
    section: DossierSectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new dossier section."""
    # Verify submission exists and is in user's org
    _assert_submission_in_org(section.submission_id, db, current_user)
    
    # Verify parent section exists if specified
    if section.parent_section_id:
        parent_section = db.query(DossierSection).filter(
            and_(
                DossierSection.id == section.parent_section_id,
                DossierSection.submission_id == section.submission_id
            )
        ).first()
        if not parent_section:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent section not found"
            )
    
    db_section = DossierSection(**section.model_dump())
    db.add(db_section)
    db.commit()
    db.refresh(db_section)
    
    # Add computed fields
    db_section.child_sections_count = 0
    db_section.extracted_content_count = 0
    db_section.reviews_count = 0
    db_section.missing_content_alerts = 0
    
    return db_section


@router.get("/sections", response_model=PaginatedResponse)
async def list_dossier_sections(
    submission_id: UUID = Query(..., description="Submission ID to filter sections"),
    parent_section_id: Optional[UUID] = Query(None, description="Parent section ID to filter children"),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List dossier sections for a submission."""
    _assert_submission_in_org(submission_id, db, current_user)
    query = db.query(DossierSection).filter(DossierSection.submission_id == submission_id)
    
    if parent_section_id:
        query = query.filter(DossierSection.parent_section_id == parent_section_id)
    else:
        # Only root sections if no parent specified
        query = query.filter(DossierSection.parent_section_id.is_(None))
    
    # Order by section code and order index
    query = query.order_by(DossierSection.order_index, DossierSection.section_code)
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    sections = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format
    section_summaries = [
        DossierSectionSummary(
            id=section.id,
            section_code=section.section_code,
            section_title=section.section_title,
            is_required=section.is_required,
            is_completed=section.is_completed,
            completion_percentage=section.completion_percentage,
            child_sections_count=0  # Would be computed in real implementation
        )
        for section in sections
    ]
    
    return PaginatedResponse.create(
        items=section_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/sections/{section_id}", response_model=DossierSectionResponse)
async def get_dossier_section(
    section_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific dossier section by ID."""
    section = _get_scoped_section(
        section_id,
        db,
        current_user,
        options=[
            selectinload(DossierSection.child_sections),
            selectinload(DossierSection.extracted_contents),
            selectinload(DossierSection.reviews),
            selectinload(DossierSection.missing_content_alerts),
        ],
    )
    
    # Add computed fields
    section.child_sections_count = len(section.child_sections)
    section.extracted_content_count = len(section.extracted_contents)
    section.reviews_count = len(section.reviews)
    section.missing_content_alerts = len([alert for alert in section.missing_content_alerts if not alert.is_resolved])
    section.is_leaf = len(section.child_sections) == 0
    
    return section


@router.put("/sections/{section_id}", response_model=DossierSectionResponse)
async def update_dossier_section(
    section_id: UUID,
    section_update: DossierSectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a specific dossier section."""
    db_section = _get_scoped_section(section_id, db, current_user)
    
    # Update fields
    update_data = section_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_section, field, value)
    
    db.commit()
    db.refresh(db_section)
    
    # Add computed fields
    db_section.child_sections_count = 0
    db_section.extracted_content_count = 0
    db_section.reviews_count = 0
    db_section.missing_content_alerts = 0
    
    return db_section


@router.delete("/sections/{section_id}", response_model=MessageResponse)
async def delete_dossier_section(
    section_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific dossier section."""
    db_section = _get_scoped_section(section_id, db, current_user)
    
    # Check if section has children
    child_count = db.query(DossierSection).filter(DossierSection.parent_section_id == section_id).count()
    if child_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete section with child sections"
        )
    
    db.delete(db_section)
    db.commit()
    
    return MessageResponse(message="Dossier section deleted successfully")


@router.get("/structure/{submission_id}", response_model=DossierStructureResponse)
async def get_dossier_structure(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the complete hierarchical dossier structure for a submission."""
    _assert_submission_in_org(submission_id, db, current_user)
    
    # Get all sections for the submission
    sections = db.query(DossierSection).filter(
        DossierSection.submission_id == submission_id
    ).order_by(DossierSection.order_index, DossierSection.section_code).all()
    
    # Build hierarchical structure
    sections_dict = {section.id: section for section in sections}
    root_sections = []
    
    def build_section_tree(section) -> DossierSectionTree:
        # Find children
        children = [
            build_section_tree(child_section)
            for child_section in sections
            if child_section.parent_section_id == section.id
        ]
        
        # Create tree node
        section_tree = DossierSectionTree(
            id=section.id,
            submission_id=section.submission_id,
            parent_section_id=section.parent_section_id,
            section_code=section.section_code,
            section_title=section.section_title,
            section_description=section.section_description,
            is_required=section.is_required,
            is_completed=section.is_completed,
            completion_percentage=section.completion_percentage,
            order_index=section.order_index,
            template_source=section.template_source,
            content=section.content,
            ai_extracted_content=section.ai_extracted_content,
            ai_confidence_score=section.ai_confidence_score,
            created_at=section.created_at,
            updated_at=section.updated_at,
            child_sections_count=len(children),
            extracted_content_count=0,  # Would be computed
            reviews_count=0,  # Would be computed
            missing_content_alerts=0,  # Would be computed
            is_leaf=len(children) == 0,
            children=children
        )
        
        return section_tree
    
    # Build root sections
    for section in sections:
        if section.parent_section_id is None:
            root_sections.append(build_section_tree(section))
    
    # Calculate statistics
    total_sections = len(sections)
    completed_sections = sum(1 for section in sections if section.is_completed)
    required_sections = sum(1 for section in sections if section.is_required)
    completed_required_sections = sum(1 for section in sections if section.is_required and section.is_completed)
    
    overall_completion_percentage = (completed_sections / total_sections) * 100 if total_sections > 0 else 0
    
    structure = DossierStructureResponse(
        submission_id=submission_id,
        sections=root_sections,
        total_sections=total_sections,
        completed_sections=completed_sections,
        required_sections=required_sections,
        completed_required_sections=completed_required_sections,
        overall_completion_percentage=overall_completion_percentage
    )
    
    return structure


@router.post("/template/create", response_model=MessageResponse)
async def create_dossier_from_template(
    template_request: DossierTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a dossier structure from an IMDRF template."""
    _assert_submission_in_org(template_request.submission_id, db, current_user)
    try:
        dossier_service = DossierCreationService(db)
        result = dossier_service.create_dossier_from_template(
            submission_id=template_request.submission_id,
            template_name=template_request.template_name,
            template_version=template_request.template_version
        )
        
        return MessageResponse(
            message=f"Dossier created from template '{result['template_name']}' - {result['sections_created']} sections created"
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating dossier: {str(e)}"
        )


@router.get("/validate/{submission_id}", response_model=DossierValidationResult)
async def validate_dossier(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate a dossier for completeness and consistency."""
    _assert_submission_in_org(submission_id, db, current_user)
    
    try:
        dossier_service = DossierCreationService(db)
        validation_result = dossier_service.validate_dossier_completeness(submission_id)
        
        # Get sections for additional validation
        sections = db.query(DossierSection).filter(
            DossierSection.submission_id == submission_id
        ).all()
        
        validation_errors = []
        validation_warnings = []
        incomplete_sections = []
        
        # Build incomplete sections list
        for section in sections:
            if section.completion_percentage < 100:
                incomplete_sections.append({
                    "section_code": section.section_code,
                    "section_title": section.section_title,
                    "completion_percentage": section.completion_percentage
                })
        
        # Add validation rules
        if not validation_result["is_complete"]:
            validation_errors.append(f"Missing {len(validation_result['missing_required_sections'])} required sections")
        
        if len(incomplete_sections) > len(sections) * 0.5:  # More than 50% incomplete
            validation_warnings.append("More than 50% of sections are incomplete")
        
        result = DossierValidationResult(
            submission_id=submission_id,
            is_valid=validation_result["is_complete"],
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
            missing_required_sections=[
                f"{s['section_code']}: {s['section_title']}"
                for s in validation_result["missing_required_sections"]
            ],
            incomplete_sections=incomplete_sections,
            validation_date=datetime.utcnow()
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating dossier: {str(e)}"
        )


@router.get("/stats/{submission_id}", response_model=DossierStats)
async def get_dossier_stats(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get statistics for a specific dossier."""
    _assert_submission_in_org(submission_id, db, current_user)
    sections = db.query(DossierSection).filter(
        DossierSection.submission_id == submission_id
    ).all()
    
    if not sections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No dossier sections found for this submission"
        )
    
    total_sections = len(sections)
    completed_sections = sum(1 for section in sections if section.is_completed)
    in_progress_sections = sum(1 for section in sections 
                              if not section.is_completed and section.completion_percentage > 0)
    missing_sections = total_sections - completed_sections - in_progress_sections
    
    # These would be computed with proper joins in real implementation
    sections_with_content = 0
    sections_with_reviews = 0
    
    average_completion_percentage = sum(section.completion_percentage for section in sections) / total_sections
    
    stats = DossierStats(
        total_sections=total_sections,
        completed_sections=completed_sections,
        in_progress_sections=in_progress_sections,
        missing_sections=missing_sections,
        sections_with_content=sections_with_content,
        sections_with_reviews=sections_with_reviews,
        average_completion_percentage=average_completion_percentage
    )
    
    return stats


@router.get("/templates", response_model=List[DossierTemplate])
async def list_available_templates(
    regulation_type: Optional[str] = Query(None, description="Filter by regulation type"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all available IMDRF templates."""
    template_loader = IMDRFTemplateLoader()
    templates = template_loader.get_available_templates()
    
    # Filter by regulation type if specified
    if regulation_type:
        # Load each template to check its regulation type
        filtered_templates = []
        for template in templates:
            # This is a simplified filter - in reality, you'd store regulation_type in the template
            if regulation_type.lower() in template.template_name.lower():
                filtered_templates.append(template)
        return filtered_templates
    
    return templates


@router.get("/templates/{template_name}", response_model=DossierTemplate)
async def get_template(
    template_name: str,
    template_version: Optional[str] = Query(None, description="Specific version to retrieve"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific IMDRF template."""
    template_loader = IMDRFTemplateLoader()
    template = template_loader.load_template(template_name, template_version)
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_name}' not found"
        )
    
    return template


@router.post("/template/validate", response_model=Dict[str, Any])
async def validate_template(
    template_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate an IMDRF template structure."""
    validation_result = TemplateValidationService.validate_template_structure(template_data)
    return validation_result


@router.post("/auto-create/{submission_id}", response_model=MessageResponse)
async def auto_create_dossier(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Automatically create dossier structure based on product regulation type."""
    _assert_submission_in_org(submission_id, db, current_user)
    # Get submission with product info
    submission = db.query(Submission).options(
        joinedload(Submission.product)
    ).filter(Submission.id == submission_id).first()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    try:
        dossier_service = DossierCreationService(db)
        result = dossier_service.create_dossier_for_product_type(
            submission_id=submission_id,
            regulation_type=submission.product.regulation_type
        )
        
        return MessageResponse(
            message=f"Dossier auto-created for {submission.product.regulation_type} device - {result['sections_created']} sections created"
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error auto-creating dossier: {str(e)}"
        )