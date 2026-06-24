"""
Projects API router with full CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.projects.models import Project
from app.projects.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectSummary,
    ProjectListResponse,
    ProjectStats
)
from app.core.schemas import PaginationParams, PaginatedResponse, MessageResponse

router = APIRouter()


def _scope_projects(query, current_user: User):
    """Restrict a Project query to the current user's org (no-op for super admins)."""
    if current_user.is_super_admin:
        return query
    return query.filter(Project.organization_id == current_user.organization_id)


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new project in the current user's organization."""
    db_project = Project(
        **project.model_dump(),
        organization_id=current_user.organization_id,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    
    # Add computed fields
    db_project.products_count = 0
    db_project.submissions_count = 0
    db_project.files_count = 0
    
    return db_project


@router.get("/", response_model=PaginatedResponse)
async def list_projects(
    pagination: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, description="Filter by project status"),
    client_name: Optional[str] = Query(None, description="Filter by client name"),
    search: Optional[str] = Query(None, description="Search in project name or description"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List projects with optional filtering and pagination."""
    query = _scope_projects(db.query(Project), current_user)
    
    # Apply filters
    if status_filter:
        query = query.filter(Project.status == status_filter)
    
    if client_name:
        query = query.filter(Project.client_name.ilike(f"%{client_name}%"))
    
    if search:
        query = query.filter(
            or_(
                Project.name.ilike(f"%{search}%"),
                Project.description.ilike(f"%{search}%")
            )
        )
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    projects = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format with computed fields
    project_summaries = []
    for project in projects:
        # Get counts (in real implementation, these would be computed more efficiently)
        products_count = len(project.products) if hasattr(project, 'products') else 0
        submissions_count = len(project.submissions) if hasattr(project, 'submissions') else 0
        
        project_summary = ProjectSummary(
            id=project.id,
            name=project.name,
            client_name=project.client_name,
            status=project.status,
            created_at=project.created_at,
            products_count=products_count,
            submissions_count=submissions_count
        )
        project_summaries.append(project_summary)
    
    return PaginatedResponse.create(
        items=project_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific project by ID."""
    project = _scope_projects(
        db.query(Project).options(
            selectinload(Project.products),
            selectinload(Project.submissions),
            selectinload(Project.files),
        ),
        current_user,
    ).filter(Project.id == project_id).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Add computed fields
    project.products_count = len(project.products)
    project.submissions_count = len(project.submissions)
    project.files_count = len(project.files)
    
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a specific project."""
    db_project = _scope_projects(db.query(Project), current_user).filter(
        Project.id == project_id
    ).first()
    
    if not db_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Update fields
    update_data = project_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_project, field, value)
    
    db.commit()
    db.refresh(db_project)
    
    # Add computed fields
    db_project.products_count = len(db_project.products) if hasattr(db_project, 'products') else 0
    db_project.submissions_count = len(db_project.submissions) if hasattr(db_project, 'submissions') else 0
    db_project.files_count = len(db_project.files) if hasattr(db_project, 'files') else 0
    
    return db_project


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a specific project."""
    db_project = _scope_projects(db.query(Project), current_user).filter(
        Project.id == project_id
    ).first()
    
    if not db_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    db.delete(db_project)
    db.commit()
    
    return MessageResponse(message="Project deleted successfully")


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get statistics for a specific project."""
    project = _scope_projects(db.query(Project), current_user).filter(
        Project.id == project_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # In a real implementation, these would be more sophisticated queries
    stats = ProjectStats(
        total_projects=1,
        active_projects=1 if project.status == "active" else 0,
        completed_projects=1 if project.status == "completed" else 0,
        on_hold_projects=1 if project.status == "on_hold" else 0,
        cancelled_projects=1 if project.status == "cancelled" else 0,
        projects_by_month=[]  # Would be computed from creation dates
    )
    
    return stats


@router.get("/stats", response_model=ProjectStats, dependencies=[Depends(get_db)])
async def get_overall_project_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get overall project statistics."""
    # Count projects by status
    base = _scope_projects(db.query(Project), current_user)
    status_counts = _scope_projects(
        db.query(Project.status, func.count(Project.id)),
        current_user,
    ).group_by(Project.status).all()
    
    total_projects = base.count()
    
    # Initialize counts
    active_projects = 0
    completed_projects = 0
    on_hold_projects = 0
    cancelled_projects = 0
    
    # Map status counts
    for status_val, count in status_counts:
        if status_val == "active":
            active_projects = count
        elif status_val == "completed":
            completed_projects = count
        elif status_val == "on_hold":
            on_hold_projects = count
        elif status_val == "cancelled":
            cancelled_projects = count
    
    stats = ProjectStats(
        total_projects=total_projects,
        active_projects=active_projects,
        completed_projects=completed_projects,
        on_hold_projects=on_hold_projects,
        cancelled_projects=cancelled_projects,
        projects_by_month=[]  # Would compute monthly creation trends
    )
    
    return stats