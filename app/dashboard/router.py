"""
Dashboard API endpoints for statistics and recent activity.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.projects.models import Project
from app.submissions.models import Submission
from app.files.models import UploadedFile

router = APIRouter()


def _scope_projects(query, current_user: User):
    if current_user.is_super_admin:
        return query
    return query.filter(Project.organization_id == current_user.organization_id)


def _scope_submissions(query, current_user: User):
    if current_user.is_super_admin:
        return query
    return query.filter(Submission.organization_id == current_user.organization_id)


def _scope_files(query, current_user: User):
    if current_user.is_super_admin:
        return query
    return query.join(Project, UploadedFile.project_id == Project.id).filter(
        Project.organization_id == current_user.organization_id
    )


@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get dashboard statistics, scoped to the caller's organization."""

    # Count projects by status (scoped)
    total_projects = _scope_projects(db.query(Project), current_user).count()
    active_projects = _scope_projects(
        db.query(Project).filter(Project.status == "active"), current_user
    ).count()

    # Count submissions (scoped)
    total_submissions = _scope_submissions(db.query(Submission), current_user).count()
    pending_reviews = _scope_submissions(
        db.query(Submission).filter(
            Submission.status.in_(["draft", "human_review"])
        ),
        current_user,
    ).count()

    # Count files processed today (scoped via project)
    today = datetime.utcnow().date()
    files_processed = _scope_files(
        db.query(UploadedFile).filter(func.date(UploadedFile.created_at) == today),
        current_user,
    ).count()

    # Count AI extractions today (placeholder - would need ExtractedContent model)
    ai_extractions_today = 0

    return {
        "total_projects": total_projects,
        "active_projects": active_projects,
        "total_submissions": total_submissions,
        "pending_reviews": pending_reviews,
        "files_processed": files_processed,
        "ai_extractions_today": ai_extractions_today,
    }


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get recent activity across the system (scoped to the caller's organization)."""

    activities = []

    # Recent projects (last 7 days)
    recent_projects = _scope_projects(
        db.query(Project).filter(
            Project.created_at >= datetime.utcnow() - timedelta(days=7)
        ),
        current_user,
    ).order_by(desc(Project.created_at)).limit(limit // 2).all()

    for project in recent_projects:
        activities.append({
            "id": f"project_{project.id}",
            "type": "project_created",
            "title": "New Project Created",
            "description": f"{project.name} - {project.status.title()} Project",
            "timestamp": project.created_at.isoformat(),
            "user": "System User",
        })

    # Recent file uploads (last 7 days)
    recent_files = _scope_files(
        db.query(UploadedFile).filter(
            UploadedFile.created_at >= datetime.utcnow() - timedelta(days=7)
        ),
        current_user,
    ).order_by(desc(UploadedFile.created_at)).limit(limit // 2).all()

    for file in recent_files:
        activities.append({
            "id": f"file_{file.id}",
            "type": "file_uploaded",
            "title": "File Uploaded",
            "description": f"{file.original_filename} ({file.file_size} bytes)",
            "timestamp": file.created_at.isoformat(),
            "user": file.uploaded_by or "Unknown User",
        })

    # Sort by timestamp and limit
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    return activities[:limit]