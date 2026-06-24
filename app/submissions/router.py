"""
Submissions API router with full CRUD operations and workflow management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.submissions.models import Submission
from app.products.models import Product
from app.projects.models import Project
from app.dossier.models import DossierSection
from app.dossier.services import DossierGenerationService, DossierContentService, LeafSectionRequiredError
from app.ai.services import AIProcessingService


def _derive_section_status(section) -> str:
    """Helper function to derive status from DossierSection model fields."""
    if section.is_completed:
        return "completed"
    elif section.completion_percentage > 0:
        return "in_progress"
    else:
        return "not_started"


def _scope_submissions(query, current_user: User):
    """Restrict a Submission query to the current user's org (no-op for super admins)."""
    if current_user.is_super_admin:
        return query
    return query.filter(Submission.organization_id == current_user.organization_id)


def _get_scoped_submission(submission_id, db: Session, current_user: User, *, options=None):
    """Fetch a submission by id, enforcing org isolation. Raises 404 on miss."""
    query = db.query(Submission)
    if options:
        query = query.options(*options)
    submission = _scope_submissions(query, current_user).filter(
        Submission.id == submission_id
    ).first()
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    return submission
from app.submissions.schemas import (
    SubmissionCreate,
    SubmissionUpdate,
    SubmissionStatusUpdate,
    SubmissionResponse,
    SubmissionWithDetails,
    SubmissionSummary,
    SubmissionListResponse,
    SubmissionWorkflowAction,
    SubmissionStats,
    SubmissionSearchFilters,
    SubmissionProgress
)
from app.core.schemas import PaginationParams, PaginatedResponse, MessageResponse

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_submission(
    submission: SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new submission."""
    # Verify project exists and belongs to the user's org (super admins bypass org check).
    project_query = db.query(Project).filter(Project.id == submission.project_id)
    if not current_user.is_super_admin:
        project_query = project_query.filter(
            Project.organization_id == current_user.organization_id
        )
    project = project_query.first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    product = db.query(Product).filter(
        and_(
            Product.id == submission.product_id,
            Product.project_id == submission.project_id
        )
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or does not belong to the specified project"
        )
    
    # Create submission (inherits org from its project).
    db_submission = Submission(
        organization_id=project.organization_id,
        project_id=submission.project_id,
        product_id=submission.product_id,
        name=submission.name,
        submission_type=submission.submission_type,
        target_submission_date=submission.target_submission_date
    )
    db.add(db_submission)
    db.commit()
    db.refresh(db_submission)
    
    # Generate dossier structure automatically based on submission type
    try:
        dossier_service = DossierGenerationService(db)
        dossier_sections = dossier_service.generate_dossier_for_submission(db_submission)
        
        sections_count = len(dossier_sections)
        message = f"Submission created successfully with {sections_count} dossier sections generated"
    except Exception as e:
        # If dossier generation fails, log the error but don't fail the submission creation
        print(f"Warning: Failed to generate dossier for submission {db_submission.id}: {str(e)}")
        message = "Submission created successfully (dossier generation failed - can be regenerated later)"
    
    # Return submission details
    return {
        "id": str(db_submission.id),
        "name": db_submission.name,
        "submission_type": db_submission.submission_type,
        "status": db_submission.status.value,
        "project_id": str(db_submission.project_id),
        "product_id": str(db_submission.product_id),
        "target_submission_date": db_submission.target_submission_date.isoformat() if db_submission.target_submission_date else None,
        "created_at": db_submission.created_at.isoformat(),
        "message": message
    }


@router.get("/", response_model=PaginatedResponse)
async def list_submissions(
    pagination: PaginationParams = Depends(),
    project_id: Optional[UUID] = Query(None, description="Filter by project ID"),
    product_id: Optional[UUID] = Query(None, description="Filter by product ID"),
    status_filter: Optional[str] = Query(None, description="Filter by submission status"),
    search: Optional[str] = Query(None, description="Search in submission name"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List submissions with optional filtering and pagination."""
    query = _scope_submissions(
        db.query(Submission).options(
            joinedload(Submission.project),
            joinedload(Submission.product),
        ),
        current_user,
    )
    
    # Apply filters
    if project_id:
        query = query.filter(Submission.project_id == project_id)
    
    if product_id:
        query = query.filter(Submission.product_id == product_id)
    
    if status_filter:
        query = query.filter(Submission.status == status_filter)
    
    if search:
        query = query.filter(Submission.name.ilike(f"%{search}%"))
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    submissions = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format
    submission_summaries = []
    for submission in submissions:
        # Calculate completion percentage (simplified)
        completion_percentage = 0.0
        if hasattr(submission, 'dossier_sections') and submission.dossier_sections:
            completed = sum(1 for section in submission.dossier_sections if section.is_completed)
            total_sections = len(submission.dossier_sections)
            completion_percentage = (completed / total_sections) * 100 if total_sections > 0 else 0
        
        submission_summary = SubmissionSummary(
            id=submission.id,
            name=submission.name,
            status=submission.status,
            target_submission_date=submission.target_submission_date,
            completion_percentage=completion_percentage,
            created_at=submission.created_at,
            product_id=submission.product_id,
            product_name=submission.product.name,
            project_id=submission.project_id,
            project_name=submission.project.name,
            submission_type=submission.submission_type
        )
        submission_summaries.append(submission_summary)
    
    return PaginatedResponse.create(
        items=submission_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific submission by ID."""
    submission = _get_scoped_submission(
        submission_id,
        db,
        current_user,
        options=[
            selectinload(Submission.dossier_sections),
            selectinload(Submission.missing_content_alerts),
            selectinload(Submission.consistency_checks),
            joinedload(Submission.project),
            joinedload(Submission.product),
        ],
    )
    
    # Calculate computed fields
    dossier_sections_count = len(submission.dossier_sections)
    completed_sections_count = sum(1 for section in submission.dossier_sections if section.is_completed)
    completion_percentage = (
        (completed_sections_count / dossier_sections_count) * 100
        if dossier_sections_count > 0 else 0.0
    )
    missing_content_alerts_count = len([alert for alert in submission.missing_content_alerts if not alert.is_resolved])
    consistency_issues_count = len([check for check in submission.consistency_checks if not check.is_resolved])
    
    # Create response with computed fields
    response_data = SubmissionResponse(
        id=submission.id,
        name=submission.name,
        submission_type=submission.submission_type,
        health_canada_reference=submission.health_canada_reference,
        target_submission_date=submission.target_submission_date,
        project_id=submission.project_id,
        product_id=submission.product_id,
        status=submission.status,
        submitted_at=submission.submitted_at,
        approved_at=submission.approved_at,
        approved_by=submission.approved_by,
        created_by=getattr(submission, 'created_by', None),
        updated_by=getattr(submission, 'updated_by', None),
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        # Computed fields
        dossier_sections_count=dossier_sections_count,
        completed_sections_count=completed_sections_count,
        completion_percentage=completion_percentage,
        missing_content_alerts=missing_content_alerts_count,
        consistency_issues=consistency_issues_count
    )
    
    return response_data


@router.get("/{submission_id}/details", response_model=SubmissionWithDetails)
async def get_submission_with_details(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a submission with full project and product details."""
    submission = _get_scoped_submission(
        submission_id,
        db,
        current_user,
        options=[
            selectinload(Submission.dossier_sections),
            joinedload(Submission.project),
            joinedload(Submission.product),
        ],
    )
    
    # Create response with full details
    response_data = SubmissionResponse.model_validate(submission).model_dump()
    response_data.update({
        "project_name": submission.project.name,
        "client_name": submission.project.client_name,
        "product_name": submission.product.name,
        "device_type": submission.product.device_type,
        "regulation_type": submission.product.regulation_type
    })
    
    return SubmissionWithDetails(**response_data)


@router.put("/{submission_id}")
async def update_submission(
    submission_id: UUID,
    submission_update: SubmissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a specific submission."""
    db_submission = _get_scoped_submission(submission_id, db, current_user)
    
    # Update fields
    update_data = submission_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_submission, field, value)
    
    db.commit()
    db.refresh(db_submission)
    
    # Calculate computed fields
    dossier_sections_count = db.query(DossierSection).filter(
        DossierSection.submission_id == db_submission.id
    ).count()
    
    completed_sections_count = db.query(DossierSection).filter(
        DossierSection.submission_id == db_submission.id,
        DossierSection.is_completed == True
    ).count()
    
    completion_percentage = (completed_sections_count / dossier_sections_count * 100) if dossier_sections_count > 0 else 0.0
    
    # Return a simple dictionary to avoid Pydantic validation issues
    return {
        "id": str(db_submission.id),
        "name": db_submission.name,
        "submission_type": db_submission.submission_type,
        "status": db_submission.status.value if db_submission.status else "draft",
        "project_id": str(db_submission.project_id),
        "product_id": str(db_submission.product_id),
        "health_canada_reference": db_submission.health_canada_reference,
        "target_submission_date": db_submission.target_submission_date.isoformat() if db_submission.target_submission_date else None,
        "submitted_at": db_submission.submitted_at.isoformat() if db_submission.submitted_at else None,
        "approved_at": db_submission.approved_at.isoformat() if db_submission.approved_at else None,
        "approved_by": db_submission.approved_by,
        "created_by": db_submission.created_by,
        "updated_by": db_submission.updated_by,
        "created_at": db_submission.created_at.isoformat(),
        "updated_at": db_submission.updated_at.isoformat(),
        "dossier_sections_count": dossier_sections_count,
        "completed_sections_count": completed_sections_count,
        "completion_percentage": completion_percentage,
        "missing_content_alerts": 0,
        "consistency_issues": 0,
        "message": "Submission updated successfully"
    }


@router.patch("/{submission_id}/status", response_model=SubmissionResponse)
async def update_submission_status(
    submission_id: UUID,
    status_update: SubmissionStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update submission status with workflow validation."""
    db_submission = _get_scoped_submission(submission_id, db, current_user)
    
    # Validate status transition (simplified workflow)
    current_status = db_submission.status
    new_status = status_update.status
    
    # Define valid transitions
    valid_transitions = {
        "draft": ["ai_processing"],
        "ai_processing": ["human_review", "draft"],
        "human_review": ["approved", "rejected", "draft"],
        "approved": ["submitted"],
        "rejected": ["draft"],
        "submitted": []  # Final state
    }
    
    if new_status not in valid_transitions.get(current_status, []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition from {current_status} to {new_status}"
        )
    
    # Update status and related fields
    db_submission.status = new_status
    
    if new_status == "approved":
        db_submission.approved_at = datetime.utcnow()
        db_submission.approved_by = status_update.approved_by
    elif new_status == "submitted":
        db_submission.submitted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_submission)
    
    # Add computed fields
    db_submission.dossier_sections_count = 0
    db_submission.completed_sections_count = 0
    db_submission.completion_percentage = 0.0
    # missing_content_alerts is a relationship, not a computed field
    # consistency_checks is a relationship, not a computed field
    
    return db_submission


@router.post("/{submission_id}/workflow", response_model=MessageResponse)
async def execute_workflow_action(
    submission_id: UUID,
    action: SubmissionWorkflowAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a workflow action on a submission."""
    submission = _get_scoped_submission(submission_id, db, current_user)
    
    # Execute action based on type
    if action.action == "start_ai_processing":
        if submission.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only start AI processing from draft status"
            )
        submission.status = "ai_processing"
        message = "AI processing started"
        
    elif action.action == "submit_for_review":
        if submission.status != "ai_processing":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only submit for review from AI processing status"
            )
        submission.status = "human_review"
        message = "Submitted for human review"
        
    elif action.action == "approve":
        if submission.status != "human_review":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only approve from human review status"
            )
        submission.status = "approved"
        submission.approved_at = datetime.utcnow()
        submission.approved_by = action.performed_by
        message = "Submission approved"
        
    elif action.action == "reject":
        if submission.status not in ["human_review", "approved"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only reject from human review or approved status"
            )
        submission.status = "rejected"
        message = "Submission rejected"
        
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown workflow action: {action.action}"
        )
    
    db.commit()
    
    return MessageResponse(message=message)


@router.get("/{submission_id}/progress", response_model=SubmissionProgress)
async def get_submission_progress(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed progress information for a submission."""
    submission = _get_scoped_submission(
        submission_id,
        db,
        current_user,
        options=[selectinload(Submission.dossier_sections)],
    )
    
    # Calculate progress metrics
    total_sections = len(submission.dossier_sections)
    completed_sections = sum(1 for section in submission.dossier_sections if section.is_completed)
    in_progress_sections = sum(1 for section in submission.dossier_sections 
                              if not section.is_completed and section.completion_percentage > 0)
    missing_sections = total_sections - completed_sections - in_progress_sections
    
    completion_percentage = (completed_sections / total_sections) * 100 if total_sections > 0 else 0
    
    # Generate next steps based on current status
    next_steps = []
    if submission.status == "draft":
        next_steps = ["Complete missing sections", "Upload required documents", "Start AI processing"]
    elif submission.status == "ai_processing":
        next_steps = ["Wait for AI processing to complete", "Review extracted content"]
    elif submission.status == "human_review":
        next_steps = ["Review AI-generated content", "Approve or request changes"]
    elif submission.status == "approved":
        next_steps = ["Final review", "Submit to Health Canada"]
    
    progress = SubmissionProgress(
        submission_id=submission_id,
        total_sections=total_sections,
        completed_sections=completed_sections,
        in_progress_sections=in_progress_sections,
        missing_sections=missing_sections,
        completion_percentage=completion_percentage,
        last_updated=submission.updated_at,
        next_steps=next_steps
    )
    
    return progress


@router.delete("/{submission_id}", response_model=MessageResponse)
async def delete_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific submission."""
    db_submission = _get_scoped_submission(submission_id, db, current_user)
    
    # Check if submission can be deleted (business rule)
    if db_submission.status == "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete submitted submissions"
        )
    
    db.delete(db_submission)
    db.commit()
    
    return MessageResponse(message="Submission deleted successfully")


@router.get("/stats/overview", response_model=SubmissionStats)
async def get_submission_stats(
    project_id: Optional[UUID] = Query(None, description="Filter stats by project"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get submission statistics."""
    query = _scope_submissions(db.query(Submission), current_user)
    
    if project_id:
        query = query.filter(Submission.project_id == project_id)
    
    total_submissions = query.count()
    
    # Count by status
    draft_submissions = query.filter(Submission.status == "draft").count()
    in_review_submissions = query.filter(Submission.status.in_(["ai_processing", "human_review"])).count()
    approved_submissions = query.filter(Submission.status == "approved").count()
    submitted_submissions = query.filter(Submission.status == "submitted").count()
    
    # Calculate average completion time (simplified)
    average_completion_time = None  # Would calculate from created_at to approved_at
    
    stats = SubmissionStats(
        total_submissions=total_submissions,
        draft_submissions=draft_submissions,
        in_review_submissions=in_review_submissions,
        approved_submissions=approved_submissions,
        submitted_submissions=submitted_submissions,
        submissions_by_month=[],  # Would compute monthly trends
        average_completion_time=average_completion_time
    )
    
    return stats


# Dossier Management Endpoints

@router.get("/{submission_id}/dossier")
async def get_submission_dossier(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the complete dossier structure for a submission."""
    submission = _get_scoped_submission(submission_id, db, current_user)
    
    dossier_service = DossierGenerationService(db)
    dossier_structure = dossier_service.get_dossier_structure(submission_id)
    
    return {
        "submission_id": str(submission_id),
        "submission_name": submission.name,
        "submission_type": submission.submission_type,
        "dossier_sections": dossier_structure,
        "total_sections": len(dossier_structure),
        "template_info": {
            "template_name": "IMDRF Template",
            "version": "1.0"
        }
    }


@router.post("/{submission_id}/dossier/regenerate")
async def regenerate_submission_dossier(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate the dossier structure for a submission."""
    try:
        submission = _get_scoped_submission(submission_id, db, current_user)
        
        # If submission type is empty, set a default
        if not submission.submission_type or submission.submission_type.strip() == "":
            print(f"Submission {submission_id} has empty submission_type, setting default to 'medical_device_license'")
            submission.submission_type = "medical_device_license"
            db.commit()
        
        dossier_service = DossierGenerationService(db)
        dossier_sections = dossier_service.regenerate_dossier(submission_id)
        
        return {
            "message": f"Dossier regenerated successfully with {len(dossier_sections)} sections",
            "sections_count": len(dossier_sections),
            "submission_id": str(submission_id),
            "submission_type": submission.submission_type
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        print(f"Error regenerating dossier: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate dossier: {str(e)}"
        )


@router.get("/{submission_id}/dossier/sections/{section_id}")
async def get_dossier_section(
    submission_id: UUID,
    section_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed information for a specific dossier section."""
    # Org-scoped submission lookup acts as the access check.
    _get_scoped_submission(submission_id, db, current_user)
    section = db.query(DossierSection).filter(
        and_(
            DossierSection.id == section_id,
            DossierSection.submission_id == submission_id
        )
    ).first()
    
    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier section not found"
        )
    
    # Derive status from is_completed
    status = _derive_section_status(section)

    # Section is a leaf iff no other section lists it as parent
    is_leaf = db.query(DossierSection.id).filter(
        DossierSection.parent_section_id == section.id
    ).first() is None
    
    # Generate placeholder content based on section info
    placeholder_content = f"""# {section.section_title}

## Section Description
{section.section_description or 'No description available.'}

## Instructions
This section is part of the IMDRF regulatory submission template.

Please provide the required documentation and information for this section.

---
*This is a placeholder. Replace with actual submission content.*
"""
    
    return {
        "id": str(section.id),
        "section_code": section.section_code,
        "section_title": section.section_title,
        "section_description": section.section_description or "",
        "is_required": section.is_required,
        "status": status,
        "completion_percentage": section.completion_percentage,
        "content_requirements": section.content_requirements or [],
        "content": section.content or "",
        "placeholder_content": section.placeholder_content or placeholder_content,
        "ai_extracted_content": section.ai_extracted_content or "",
        "ai_confidence_score": section.ai_confidence_score or 0.0,
        "is_leaf": is_leaf,
        "created_at": section.created_at.isoformat(),
        "updated_at": section.updated_at.isoformat()
    }


@router.put("/{submission_id}/dossier/sections/{section_id}/content")
async def update_dossier_section_content(
    submission_id: UUID,
    section_id: UUID,
    content_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update content for a specific dossier section."""
    # Org-scoped submission lookup acts as the access check.
    _get_scoped_submission(submission_id, db, current_user)
    # Verify section exists and belongs to submission
    section = db.query(DossierSection).filter(
        and_(
            DossierSection.id == section_id,
            DossierSection.submission_id == submission_id
        )
    ).first()
    
    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier section not found"
        )
    
    try:
        content_service = DossierContentService(db)
        updated_section = content_service.update_section_content(
            section_id=section_id,
            content=content_data.get("content", ""),
            updated_by=content_data.get("updated_by")
        )
        
        # Derive status from updated section
        section_status = _derive_section_status(updated_section)
        
        return {
            "message": "Section content updated successfully",
            "section_id": str(section_id),
            "status": section_status,
            "completion_percentage": updated_section.completion_percentage
        }
    except LeafSectionRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update section content: {str(e)}"
        )


@router.post("/{submission_id}/dossier/sections/{section_id}/complete")
async def mark_dossier_section_complete(
    submission_id: UUID,
    section_id: UUID,
    completion_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a dossier section as complete."""
    # Org-scoped submission lookup acts as the access check.
    _get_scoped_submission(submission_id, db, current_user)
    # Verify section exists and belongs to submission
    section = db.query(DossierSection).filter(
        and_(
            DossierSection.id == section_id,
            DossierSection.submission_id == submission_id
        )
    ).first()
    
    if not section:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier section not found"
        )
    
    try:
        content_service = DossierContentService(db)
        updated_section = content_service.mark_section_complete(
            section_id=section_id,
            completed_by=completion_data.get("completed_by")
        )
        
        # Derive status from updated section
        section_status = _derive_section_status(updated_section)
        
        return {
            "message": "Section marked as complete",
            "section_id": str(section_id),
            "status": section_status,
            "completion_percentage": updated_section.completion_percentage
        }
    except LeafSectionRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark section complete: {str(e)}"
        )