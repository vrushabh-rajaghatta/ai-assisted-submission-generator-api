"""
Validation API router for consistency checks and missing content alerts.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.validation.models import MissingContent, ConsistencyCheck
from app.submissions.models import Submission
from app.validation.schemas import (
    MissingContentCreate,
    MissingContentUpdate,
    MissingContentResponse,
    MissingContentWithContext,
    ConsistencyCheckCreate,
    ConsistencyCheckUpdate,
    ConsistencyCheckResponse,
    ConsistencyCheckWithContext,
    ValidationRunRequest,
    ValidationRunResponse,
    ValidationSummary,
    ValidationStats
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


def _scope_via_submission(query, model, current_user: User):
    """Restrict a MissingContent or ConsistencyCheck query via its parent submission."""
    if current_user.is_super_admin:
        return query
    return query.join(Submission, model.submission_id == Submission.id).filter(
        Submission.organization_id == current_user.organization_id
    )


def _get_scoped_alert(alert_id: UUID, db: Session, current_user: User) -> MissingContent:
    alert = db.query(MissingContent).filter(MissingContent.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Missing content alert not found",
        )
    if not current_user.is_super_admin:
        submission = db.query(Submission).filter(
            Submission.id == alert.submission_id
        ).first()
        if not submission or submission.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Missing content alert not found",
            )
    return alert


def _get_scoped_check(check_id: UUID, db: Session, current_user: User) -> ConsistencyCheck:
    check = db.query(ConsistencyCheck).filter(ConsistencyCheck.id == check_id).first()
    if not check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consistency check not found",
        )
    if not current_user.is_super_admin:
        submission = db.query(Submission).filter(
            Submission.id == check.submission_id
        ).first()
        if not submission or submission.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Consistency check not found",
            )
    return check


@router.post("/missing-content", response_model=MissingContentResponse, status_code=status.HTTP_201_CREATED)
async def create_missing_content_alert(
    alert: MissingContentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new missing content alert."""
    _assert_submission_in_org(alert.submission_id, db, current_user)

    db_alert = MissingContent(**alert.model_dump())
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)
    
    return db_alert


@router.get("/missing-content", response_model=PaginatedResponse)
async def list_missing_content_alerts(
    pagination: PaginationParams = Depends(),
    submission_id: Optional[UUID] = Query(None, description="Filter by submission ID"),
    alert_type: Optional[str] = Query(None, description="Filter by alert type"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    is_resolved: Optional[bool] = Query(None, description="Filter by resolution status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List missing content alerts with optional filtering."""
    query = _scope_via_submission(
        db.query(MissingContent).options(
            joinedload(MissingContent.submission),
            joinedload(MissingContent.dossier_section)
        ),
        MissingContent,
        current_user,
    )
    
    # Apply filters
    if submission_id:
        query = query.filter(MissingContent.submission_id == submission_id)
    
    if alert_type:
        query = query.filter(MissingContent.alert_type == alert_type)
    
    if severity:
        query = query.filter(MissingContent.severity == severity)
    
    if is_resolved is not None:
        query = query.filter(MissingContent.is_resolved == is_resolved)
    
    # Order by severity and creation date
    query = query.order_by(
        MissingContent.severity.desc(),
        MissingContent.created_at.desc()
    )
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    alerts = query.offset(pagination.offset).limit(pagination.limit).all()
    
    return PaginatedResponse.create(
        items=alerts,
        total=total,
        pagination=pagination
    )


@router.get("/missing-content/{alert_id}", response_model=MissingContentResponse)
async def get_missing_content_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific missing content alert by ID."""
    alert = _get_scoped_alert(alert_id, db, current_user)
    return alert


@router.put("/missing-content/{alert_id}", response_model=MissingContentResponse)
async def update_missing_content_alert(
    alert_id: UUID,
    alert_update: MissingContentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a missing content alert."""
    db_alert = _get_scoped_alert(alert_id, db, current_user)
    
    # Update fields
    update_data = alert_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_alert, field, value)
    
    # Set resolved timestamp if marking as resolved
    if alert_update.is_resolved and not db_alert.is_resolved:
        db_alert.resolved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_alert)
    
    return db_alert


@router.post("/consistency-checks", response_model=ConsistencyCheckResponse, status_code=status.HTTP_201_CREATED)
async def create_consistency_check(
    check: ConsistencyCheckCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new consistency check."""
    _assert_submission_in_org(check.submission_id, db, current_user)

    db_check = ConsistencyCheck(**check.model_dump())
    db.add(db_check)
    db.commit()
    db.refresh(db_check)
    
    return db_check


@router.get("/consistency-checks", response_model=PaginatedResponse)
async def list_consistency_checks(
    pagination: PaginationParams = Depends(),
    submission_id: Optional[UUID] = Query(None, description="Filter by submission ID"),
    check_type: Optional[str] = Query(None, description="Filter by check type"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    is_resolved: Optional[bool] = Query(None, description="Filter by resolution status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List consistency checks with optional filtering."""
    query = _scope_via_submission(
        db.query(ConsistencyCheck).options(joinedload(ConsistencyCheck.submission)),
        ConsistencyCheck,
        current_user,
    )
    
    # Apply filters
    if submission_id:
        query = query.filter(ConsistencyCheck.submission_id == submission_id)
    
    if check_type:
        query = query.filter(ConsistencyCheck.check_type == check_type)
    
    if severity:
        query = query.filter(ConsistencyCheck.severity == severity)
    
    if is_resolved is not None:
        query = query.filter(ConsistencyCheck.is_resolved == is_resolved)
    
    # Order by severity and creation date
    query = query.order_by(
        ConsistencyCheck.severity.desc(),
        ConsistencyCheck.created_at.desc()
    )
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    checks = query.offset(pagination.offset).limit(pagination.limit).all()
    
    return PaginatedResponse.create(
        items=checks,
        total=total,
        pagination=pagination
    )


@router.get("/consistency-checks/{check_id}", response_model=ConsistencyCheckResponse)
async def get_consistency_check(
    check_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific consistency check by ID."""
    check = _get_scoped_check(check_id, db, current_user)
    return check


@router.put("/consistency-checks/{check_id}", response_model=ConsistencyCheckResponse)
async def update_consistency_check(
    check_id: UUID,
    check_update: ConsistencyCheckUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a consistency check."""
    db_check = _get_scoped_check(check_id, db, current_user)
    
    # Update fields
    update_data = check_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_check, field, value)
    
    # Set resolved timestamp if marking as resolved
    if check_update.is_resolved and not db_check.is_resolved:
        db_check.resolved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_check)
    
    return db_check


@router.post("/run", response_model=ValidationRunResponse)
async def run_validation(
    validation_request: ValidationRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run validation checks on a submission."""
    _assert_submission_in_org(validation_request.submission_id, db, current_user)
    
    # Generate a validation run ID
    validation_run_id = uuid4()
    started_at = datetime.utcnow()
    
    # In a real implementation, this would queue validation jobs
    # For now, we'll simulate immediate completion
    
    # Count existing issues
    missing_content_count = db.query(MissingContent).filter(
        and_(
            MissingContent.submission_id == validation_request.submission_id,
            MissingContent.is_resolved == False
        )
    ).count()
    
    consistency_issues_count = db.query(ConsistencyCheck).filter(
        and_(
            ConsistencyCheck.submission_id == validation_request.submission_id,
            ConsistencyCheck.is_resolved == False
        )
    ).count()
    
    total_issues = missing_content_count + consistency_issues_count
    
    # Simulate issue severity distribution
    critical_issues = max(0, total_issues // 10)
    high_issues = max(0, total_issues // 5)
    medium_issues = max(0, total_issues // 3)
    low_issues = total_issues - critical_issues - high_issues - medium_issues
    
    response = ValidationRunResponse(
        submission_id=validation_request.submission_id,
        validation_run_id=validation_run_id,
        started_at=started_at,
        completed_at=datetime.utcnow(),
        status="completed",
        total_checks=10,  # Would be actual number of checks run
        issues_found=total_issues,
        critical_issues=critical_issues,
        high_issues=high_issues,
        medium_issues=medium_issues,
        low_issues=low_issues
    )
    
    return response


@router.get("/summary/{submission_id}", response_model=ValidationSummary)
async def get_validation_summary(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get validation summary for a submission."""
    _assert_submission_in_org(submission_id, db, current_user)
    
    # Count missing content alerts
    total_missing_content = db.query(MissingContent).filter(
        MissingContent.submission_id == submission_id
    ).count()
    
    unresolved_missing_content = db.query(MissingContent).filter(
        and_(
            MissingContent.submission_id == submission_id,
            MissingContent.is_resolved == False
        )
    ).count()
    
    # Count consistency issues
    total_consistency_issues = db.query(ConsistencyCheck).filter(
        ConsistencyCheck.submission_id == submission_id
    ).count()
    
    unresolved_consistency_issues = db.query(ConsistencyCheck).filter(
        and_(
            ConsistencyCheck.submission_id == submission_id,
            ConsistencyCheck.is_resolved == False
        )
    ).count()
    
    # Count critical issues
    critical_issues = db.query(MissingContent).filter(
        and_(
            MissingContent.submission_id == submission_id,
            MissingContent.severity == "critical",
            MissingContent.is_resolved == False
        )
    ).count()
    
    critical_issues += db.query(ConsistencyCheck).filter(
        and_(
            ConsistencyCheck.submission_id == submission_id,
            ConsistencyCheck.severity == "critical",
            ConsistencyCheck.is_resolved == False
        )
    ).count()
    
    # Calculate validation score (simplified)
    total_issues = unresolved_missing_content + unresolved_consistency_issues
    validation_score = max(0, 100 - (total_issues * 5))  # Deduct 5 points per issue
    
    # Determine if submission is ready
    is_submission_ready = critical_issues == 0 and total_issues <= 2
    
    summary = ValidationSummary(
        submission_id=submission_id,
        last_validated_at=datetime.utcnow(),  # Would be actual last validation time
        total_missing_content=total_missing_content,
        unresolved_missing_content=unresolved_missing_content,
        total_consistency_issues=total_consistency_issues,
        unresolved_consistency_issues=unresolved_consistency_issues,
        critical_issues=critical_issues,
        validation_score=validation_score,
        is_submission_ready=is_submission_ready
    )
    
    return summary


@router.get("/stats/overview", response_model=ValidationStats)
async def get_validation_stats(
    project_id: Optional[UUID] = Query(None, description="Filter stats by project"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get validation statistics."""
    missing_content_query = _scope_via_submission(
        db.query(MissingContent), MissingContent, current_user
    )
    consistency_check_query = _scope_via_submission(
        db.query(ConsistencyCheck), ConsistencyCheck, current_user
    )

    if project_id:
        missing_content_query = missing_content_query.filter(
            Submission.project_id == project_id
        )
        consistency_check_query = consistency_check_query.filter(
            Submission.project_id == project_id
        )

    # Count validation runs (simplified)
    total_validation_runs = 100  # Would be actual count
    successful_runs = 95
    failed_runs = 5

    # Calculate average issues per submission
    total_issues = missing_content_query.count() + consistency_check_query.count()
    total_submissions_q = db.query(Submission)
    if not current_user.is_super_admin:
        total_submissions_q = total_submissions_q.filter(
            Submission.organization_id == current_user.organization_id
        )
    total_submissions = total_submissions_q.count()
    average_issues_per_submission = total_issues / max(1, total_submissions)
    
    # Most common issues (simplified)
    most_common_issues = [
        {"issue_type": "missing_section", "count": 25},
        {"issue_type": "incomplete_content", "count": 18},
        {"issue_type": "device_name_mismatch", "count": 12}
    ]
    
    # Resolution rate
    resolved_issues = missing_content_query.filter(MissingContent.is_resolved == True).count()
    resolved_issues += consistency_check_query.filter(ConsistencyCheck.is_resolved == True).count()
    resolution_rate = (resolved_issues / max(1, total_issues)) * 100
    
    stats = ValidationStats(
        total_validation_runs=total_validation_runs,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        average_issues_per_submission=average_issues_per_submission,
        most_common_issues=most_common_issues,
        validation_trends=[],  # Would be computed for charts
        resolution_rate=resolution_rate
    )
    
    return stats