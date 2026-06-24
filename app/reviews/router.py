"""
Reviews API router for human review workflow management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload, joinedload, aliased
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.reviews.models import HumanReview, ReviewableType
from app.submissions.models import Submission
from app.dossier.models import DossierSection
from app.files.models import UploadedFile, ExtractedContent
from app.projects.models import Project
from app.reviews.schemas import (
    HumanReviewCreate,
    HumanReviewUpdate,
    ReviewSubmission,
    HumanReviewResponse,
    HumanReviewWithContext,
    HumanReviewSummary,
    ReviewListResponse,
    ReviewWorkflowAction,
    ReviewAssignment,
    ReviewStats
)
from app.core.schemas import PaginationParams, PaginatedResponse, MessageResponse

router = APIRouter()


def _review_org_id(review: HumanReview, db: Session) -> Optional[UUID]:
    """Resolve the organization that owns the entity this review points to."""
    if review.reviewable_type == ReviewableType.SUBMISSION or review.submission_id:
        sub_id = review.submission_id or review.reviewable_id
        submission = db.query(Submission).filter(Submission.id == sub_id).first()
        return submission.organization_id if submission else None
    if review.reviewable_type == ReviewableType.DOSSIER_SECTION or review.dossier_section_id:
        sec_id = review.dossier_section_id or review.reviewable_id
        section = db.query(DossierSection).filter(DossierSection.id == sec_id).first()
        if not section:
            return None
        submission = db.query(Submission).filter(
            Submission.id == section.submission_id
        ).first()
        return submission.organization_id if submission else None
    if review.reviewable_type == ReviewableType.EXTRACTED_CONTENT or review.extracted_content_id:
        content_id = review.extracted_content_id or review.reviewable_id
        content = db.query(ExtractedContent).filter(
            ExtractedContent.id == content_id
        ).first()
        if not content:
            return None
        file = db.query(UploadedFile).filter(UploadedFile.id == content.file_id).first()
        if not file:
            return None
        project = db.query(Project).filter(Project.id == file.project_id).first()
        return project.organization_id if project else None
    return None


def _assert_target_in_org(
    reviewable_type: str,
    reviewable_id: UUID,
    db: Session,
    current_user: User,
) -> None:
    """Ensure the entity to be reviewed is in the user's org before allowing a review."""
    if current_user.is_super_admin:
        return
    org_id = current_user.organization_id
    if reviewable_type == "submission":
        submission = db.query(Submission).filter(Submission.id == reviewable_id).first()
        if not submission or submission.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )
    elif reviewable_type == "dossier_section":
        section = db.query(DossierSection).filter(
            DossierSection.id == reviewable_id
        ).first()
        if not section:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )
        submission = db.query(Submission).filter(
            Submission.id == section.submission_id
        ).first()
        if not submission or submission.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )
    elif reviewable_type == "extracted_content":
        content = db.query(ExtractedContent).filter(
            ExtractedContent.id == reviewable_id
        ).first()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )
        file = db.query(UploadedFile).filter(UploadedFile.id == content.file_id).first()
        if not file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )
        project = db.query(Project).filter(Project.id == file.project_id).first()
        if not project or project.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reviewable entity not found",
            )


def _scope_reviews(query, db: Session, current_user: User):
    """Restrict review query to reviews whose target entity is in user's org.

    Uses outer joins through all three possible target relationships and keeps
    rows where any path resolves to the user's org.
    """
    if current_user.is_super_admin:
        return query
    org_id = current_user.organization_id
    sec_sub = aliased(Submission)
    return (
        query
        .outerjoin(DossierSection, HumanReview.dossier_section_id == DossierSection.id)
        .outerjoin(sec_sub, DossierSection.submission_id == sec_sub.id)
        .outerjoin(Submission, HumanReview.submission_id == Submission.id)
        .outerjoin(ExtractedContent, HumanReview.extracted_content_id == ExtractedContent.id)
        .outerjoin(UploadedFile, ExtractedContent.file_id == UploadedFile.id)
        .outerjoin(Project, UploadedFile.project_id == Project.id)
        .filter(
            or_(
                sec_sub.organization_id == org_id,
                Submission.organization_id == org_id,
                Project.organization_id == org_id,
            )
        )
    )


def _get_scoped_review(review_id: UUID, db: Session, current_user: User) -> HumanReview:
    review = db.query(HumanReview).filter(HumanReview.id == review_id).first()
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )
    if not current_user.is_super_admin:
        org_id = _review_org_id(review, db)
        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found",
            )
    return review


@router.post("/", response_model=HumanReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review: HumanReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new review."""
    # Verify the reviewable entity is in user's org
    _assert_target_in_org(
        review.reviewable_type, review.reviewable_id, db, current_user
    )

    # Set the appropriate foreign key based on reviewable_type
    review_data = review.model_dump()
    if review.reviewable_type == "dossier_section":
        review_data["dossier_section_id"] = review.reviewable_id
    elif review.reviewable_type == "submission":
        review_data["submission_id"] = review.reviewable_id
    elif review.reviewable_type == "extracted_content":
        review_data["extracted_content_id"] = review.reviewable_id
    
    db_review = HumanReview(**review_data)
    db.add(db_review)
    db.commit()
    db.refresh(db_review)
    
    return db_review


@router.get("/", response_model=PaginatedResponse)
async def list_reviews(
    pagination: PaginationParams = Depends(),
    reviewable_type: Optional[str] = Query(None, description="Filter by reviewable type"),
    review_status: Optional[str] = Query(None, description="Filter by review status"),
    reviewer_name: Optional[str] = Query(None, description="Filter by reviewer name"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List reviews with optional filtering and pagination."""
    query = _scope_reviews(db.query(HumanReview), db, current_user)
    
    # Apply filters
    if reviewable_type:
        query = query.filter(HumanReview.reviewable_type == reviewable_type)
    
    if review_status:
        query = query.filter(HumanReview.review_status == review_status)
    
    if reviewer_name:
        query = query.filter(HumanReview.reviewer_name.ilike(f"%{reviewer_name}%"))
    
    # Order by creation date (newest first)
    query = query.order_by(HumanReview.created_at.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    reviews = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format
    review_summaries = [
        HumanReviewSummary(
            id=review.id,
            reviewable_type=review.reviewable_type,
            review_status=review.review_status,
            reviewer_name=review.reviewer_name,
            reviewed_at=review.reviewed_at,
            created_at=review.created_at,
            entity_title=None  # Would be populated with joins in real implementation
        )
        for review in reviews
    ]
    
    return PaginatedResponse.create(
        items=review_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/{review_id}", response_model=HumanReviewResponse)
async def get_review(
    review_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific review by ID."""
    review = _get_scoped_review(review_id, db, current_user)
    return review


@router.put("/{review_id}", response_model=HumanReviewResponse)
async def update_review(
    review_id: UUID,
    review_update: HumanReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a review."""
    db_review = _get_scoped_review(review_id, db, current_user)
    
    # Update fields
    update_data = review_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_review, field, value)
    
    db.commit()
    db.refresh(db_review)
    
    return db_review


@router.post("/{review_id}/submit", response_model=HumanReviewResponse)
async def submit_review(
    review_id: UUID,
    review_submission: ReviewSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a review decision."""
    db_review = _get_scoped_review(review_id, db, current_user)
    
    # Update review with submission data
    db_review.review_status = review_submission.review_status
    db_review.review_comments = review_submission.review_comments
    db_review.suggested_changes = review_submission.suggested_changes
    db_review.reviewed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_review)
    
    return db_review


@router.delete("/{review_id}", response_model=MessageResponse)
async def delete_review(
    review_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a review."""
    db_review = _get_scoped_review(review_id, db, current_user)
    
    db.delete(db_review)
    db.commit()
    
    return MessageResponse(message="Review deleted successfully")


@router.get("/stats/overview", response_model=ReviewStats)
async def get_review_stats(
    reviewer_name: Optional[str] = Query(None, description="Filter stats by reviewer"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get review statistics."""
    query = _scope_reviews(db.query(HumanReview), db, current_user)

    if reviewer_name:
        query = query.filter(HumanReview.reviewer_name == reviewer_name)

    total_reviews = query.count()
    pending_reviews = query.filter(HumanReview.review_status == "pending").count()
    approved_reviews = query.filter(HumanReview.review_status == "approved").count()
    rejected_reviews = query.filter(HumanReview.review_status == "rejected").count()
    needs_changes_reviews = query.filter(HumanReview.review_status == "needs_changes").count()

    # Count reviews by reviewer (scoped)
    reviewer_counts = _scope_reviews(
        db.query(HumanReview.reviewer_name, func.count(HumanReview.id)),
        db,
        current_user,
    ).group_by(HumanReview.reviewer_name).all()

    reviews_by_reviewer = {reviewer: count for reviewer, count in reviewer_counts}

    # Count reviews by entity type (scoped)
    entity_type_counts = _scope_reviews(
        db.query(HumanReview.reviewable_type, func.count(HumanReview.id)),
        db,
        current_user,
    ).group_by(HumanReview.reviewable_type).all()
    
    reviews_by_entity_type = {entity_type: count for entity_type, count in entity_type_counts}
    
    # Calculate average review time (simplified)
    average_review_time = None  # Would calculate from created_at to reviewed_at
    
    # Count overdue reviews (simplified - would use due dates)
    overdue_reviews = 0
    
    stats = ReviewStats(
        total_reviews=total_reviews,
        pending_reviews=pending_reviews,
        approved_reviews=approved_reviews,
        rejected_reviews=rejected_reviews,
        needs_changes_reviews=needs_changes_reviews,
        reviews_by_reviewer=reviews_by_reviewer,
        average_review_time=average_review_time,
        reviews_by_entity_type=reviews_by_entity_type,
        overdue_reviews=overdue_reviews
    )
    
    return stats