"""
Files API router for file upload and management operations.
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import func, and_, or_

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.core.config import settings
from app.files.models import UploadedFile, ExtractedContent, FileType
from app.projects.models import Project
from app.submissions.models import Submission
from app.files.services import FileStorageService, FileValidationService, FileBatchService
from app.files.schemas import (
    FileUploadRequest,
    UploadedFileResponse,
    UploadedFileSummary,
    FileListResponse,
    FileProcessingRequest,
    FileProcessingStatus,
    ExtractedContentCreate,
    ExtractedContentUpdate,
    ExtractedContentResponse,
    ExtractedContentWithFile,
    ExtractedContentSummary,
    ContentExtractionStats,
    FileSearchFilters,
    FileBatchOperation,
    FileBatchOperationResult
)
from app.core.schemas import PaginationParams, PaginatedResponse, MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _scope_files(query, current_user: User):
    """Restrict an UploadedFile query to files whose project is in the user's org."""
    if current_user.is_super_admin:
        return query
    return query.join(Project, UploadedFile.project_id == Project.id).filter(
        Project.organization_id == current_user.organization_id
    )


def _scope_extracted_content(query, current_user: User):
    """Restrict an ExtractedContent query to content from files in the user's org."""
    if current_user.is_super_admin:
        return query
    return query.join(UploadedFile, ExtractedContent.file_id == UploadedFile.id).join(
        Project, UploadedFile.project_id == Project.id
    ).filter(Project.organization_id == current_user.organization_id)


def _assert_project_in_org(project_id: UUID, db: Session, current_user: User) -> Project:
    """Fetch project and 404 if not in user's org."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or (
        not current_user.is_super_admin
        and project.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _get_scoped_file(file_id: UUID, db: Session, current_user: User, *, options=None) -> UploadedFile:
    """Fetch file and 404 if not in user's org."""
    q = db.query(UploadedFile)
    if options:
        q = q.options(*options)
    file = q.filter(UploadedFile.id == file_id).first()
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    if not current_user.is_super_admin:
        project = db.query(Project).filter(Project.id == file.project_id).first()
        if not project or project.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found",
            )
    return file


def _get_scoped_extracted_content(
    content_id: UUID, db: Session, current_user: User
) -> ExtractedContent:
    """Fetch extracted content and 404 if its file isn't in user's org."""
    content = db.query(ExtractedContent).filter(ExtractedContent.id == content_id).first()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extracted content not found",
        )
    if not current_user.is_super_admin:
        file = db.query(UploadedFile).filter(UploadedFile.id == content.file_id).first()
        if not file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Extracted content not found",
            )
        project = db.query(Project).filter(Project.id == file.project_id).first()
        if not project or project.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Extracted content not found",
            )
    return content


def get_file_type(filename: str) -> FileType:
    """Determine file type from filename extension."""
    extension = Path(filename).suffix.lower()
    if extension == '.pdf':
        return FileType.PDF
    elif extension == '.docx':
        return FileType.DOCX
    elif extension == '.xlsx':
        return FileType.XLSX
    else:
        return FileType.OTHER


def get_mime_type(filename: str) -> str:
    """Get MIME type from filename extension."""
    extension = Path(filename).suffix.lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.doc': 'application/msword',
        '.xls': 'application/vnd.ms-excel'
    }
    return mime_types.get(extension, 'application/octet-stream')


@router.post("/upload", response_model=UploadedFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    project_id: UUID = Query(..., description="Project ID"),
    submission_id: Optional[UUID] = Query(None, description="Submission ID (optional)"),
    upload_purpose: Optional[str] = Query(None, description="Purpose of the upload"),
    uploaded_by: Optional[str] = Query(None, description="User uploading the file"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a file to the system."""
    # Verify project exists and belongs to user's org
    project = _assert_project_in_org(project_id, db, current_user)

    # Verify submission exists if provided
    if submission_id:
        submission_query = db.query(Submission).filter(
            and_(
                Submission.id == submission_id,
                Submission.project_id == project_id,
            )
        )
        if not current_user.is_super_admin:
            submission_query = submission_query.filter(
                Submission.organization_id == current_user.organization_id
            )
        submission = submission_query.first()
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found or does not belong to the specified project"
            )
    
    # Validate file
    validation = FileValidationService.validate_upload(file, settings.MAX_FILE_SIZE_MB)
    if not validation["is_valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File validation failed: {', '.join(validation['errors'])}"
        )
    
    try:
        # Save file using storage service
        storage_service = FileStorageService()
        file_metadata = await storage_service.save_uploaded_file(
            file, project_id, submission_id, upload_purpose
        )
        
        # Create database record
        db_file = UploadedFile(
            id=file_metadata["file_id"],
            project_id=project_id,
            submission_id=submission_id,
            original_filename=file_metadata["original_filename"],
            stored_filename=file_metadata["stored_filename"],
            file_path=file_metadata["file_path"],
            file_size=file_metadata["file_size"],
            file_type=file_metadata["file_type"],
            mime_type=file_metadata["mime_type"],
            file_hash=file_metadata["file_hash"],
            upload_purpose=upload_purpose,
            uploaded_by=uploaded_by
        )
        
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        # Add computed fields
        db_file.extracted_content_count = 0
        db_file.download_url = f"/api/files/{db_file.id}/download"
        db_file.preview_available = db_file.file_type in [FileType.PDF, FileType.DOCX]
        
        return db_file
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Upload failed for project=%s submission=%s filename=%r",
            project_id,
            submission_id,
            getattr(file, "filename", None),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading file: {str(e)}"
        )


@router.get("/", response_model=PaginatedResponse)
async def list_files(
    pagination: PaginationParams = Depends(),
    project_id: Optional[UUID] = Query(None, description="Filter by project ID"),
    submission_id: Optional[UUID] = Query(None, description="Filter by submission ID"),
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    is_processed: Optional[bool] = Query(None, description="Filter by processing status"),
    search: Optional[str] = Query(None, description="Search in filename or purpose"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List files with optional filtering and pagination."""
    query = _scope_files(db.query(UploadedFile), current_user)
    
    # Apply filters
    if project_id:
        query = query.filter(UploadedFile.project_id == project_id)
    
    if submission_id:
        query = query.filter(UploadedFile.submission_id == submission_id)
    
    if file_type:
        query = query.filter(UploadedFile.file_type == file_type)
    
    if is_processed is not None:
        query = query.filter(UploadedFile.is_processed == is_processed)
    
    if search:
        query = query.filter(
            or_(
                UploadedFile.original_filename.ilike(f"%{search}%"),
                UploadedFile.upload_purpose.ilike(f"%{search}%")
            )
        )
    
    # Order by creation date (newest first)
    query = query.order_by(UploadedFile.created_at.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    files = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format
    file_summaries = [
        UploadedFileSummary(
            id=file.id,
            original_filename=file.original_filename,
            file_type=file.file_type,
            file_size=file.file_size,
            upload_purpose=file.upload_purpose,
            is_processed=file.is_processed,
            created_at=file.created_at,
            extracted_content_count=len(file.extracted_contents) if hasattr(file, 'extracted_contents') else 0
        )
        for file in files
    ]
    
    return PaginatedResponse.create(
        items=file_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/{file_id}", response_model=UploadedFileResponse)
async def get_file(
    file_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific file by ID."""
    file = _get_scoped_file(
        file_id,
        db,
        current_user,
        options=[selectinload(UploadedFile.extracted_contents)],
    )

    # Add computed fields
    file.extracted_content_count = len(file.extracted_contents)
    file.download_url = f"/api/files/{file.id}/download"
    file.preview_available = file.file_type in [FileType.PDF, FileType.DOCX]

    return file


@router.get("/{file_id}/download")
async def download_file(
    file_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a file.

    Streams the file from the configured storage backend (local disk or
    S3-compatible). Integrity is verified before bytes leave the API.
    """
    file = _get_scoped_file(file_id, db, current_user)

    storage_service = FileStorageService()

    if not storage_service.file_exists(file):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in storage",
        )

    if not storage_service.verify_file_integrity(file):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File integrity check failed",
        )

    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        storage_service.open_stream(file),
        media_type=file.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{file.original_filename}"; '
                f"filename*=UTF-8''{quote(file.original_filename)}"
            ),
            "Content-Length": str(file.file_size) if file.file_size else "0",
        },
    )


@router.delete("/{file_id}", response_model=MessageResponse)
async def delete_file(
    file_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a file."""
    db_file = _get_scoped_file(file_id, db, current_user)
    
    try:
        # Delete file from storage using service
        storage_service = FileStorageService()
        storage_deleted = storage_service.delete_file(db_file)
        
        # Delete from database
        db.delete(db_file)
        db.commit()
        
        if storage_deleted:
            return MessageResponse(message=f"File '{db_file.original_filename}' deleted successfully")
        else:
            return MessageResponse(message=f"File '{db_file.original_filename}' deleted from database (file not found on disk)")
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting file: {str(e)}"
        )


@router.post("/{file_id}/process", response_model=FileProcessingStatus)
async def process_file(
    file_id: UUID,
    processing_request: FileProcessingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Request processing of a file (placeholder for AI processing)."""
    file = _get_scoped_file(file_id, db, current_user)
    
    # Mark as processed (in real implementation, this would queue for AI processing)
    file.is_processed = True
    db.commit()
    
    # Return processing status
    status_response = FileProcessingStatus(
        file_id=file_id,
        is_processing=False,
        processing_started_at=datetime.utcnow(),
        processing_completed_at=datetime.utcnow(),
        processing_error=None,
        extracted_content_count=0,
        processing_progress=100
    )
    
    return status_response


# Extracted Content endpoints
@router.post("/extracted-content", response_model=ExtractedContentResponse, status_code=status.HTTP_201_CREATED)
async def create_extracted_content(
    content: ExtractedContentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create extracted content from a file."""
    # Verify file exists and belongs to user's org
    _get_scoped_file(content.file_id, db, current_user)

    db_content = ExtractedContent(**content.model_dump())
    db.add(db_content)
    db.commit()
    db.refresh(db_content)

    # Add computed fields
    db_content.mapped_sections_count = 0
    db_content.reviews_count = 0

    return db_content


@router.get("/extracted-content", response_model=PaginatedResponse)
async def list_extracted_content(
    pagination: PaginationParams = Depends(),
    file_id: Optional[UUID] = Query(None, description="Filter by file ID"),
    content_type: Optional[str] = Query(None, description="Filter by content type"),
    reviewed: Optional[bool] = Query(None, description="Filter by review status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List extracted content with optional filtering."""
    query = _scope_extracted_content(
        db.query(ExtractedContent).options(joinedload(ExtractedContent.file)),
        current_user,
    )
    
    # Apply filters
    if file_id:
        query = query.filter(ExtractedContent.file_id == file_id)
    
    if content_type:
        query = query.filter(ExtractedContent.content_type == content_type)
    
    if reviewed is not None:
        query = query.filter(ExtractedContent.reviewed == reviewed)
    
    # Order by creation date (newest first)
    query = query.order_by(ExtractedContent.created_at.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination and get results
    content_items = query.offset(pagination.offset).limit(pagination.limit).all()
    
    # Convert to summary format
    content_summaries = [
        ExtractedContentSummary(
            id=content.id,
            content_type=content.content_type,
            content_preview=content.content_text[:200] + "..." if len(content.content_text) > 200 else content.content_text,
            confidence_score=content.confidence_score,
            page_number=content.page_number,
            reviewed=content.reviewed,
            created_at=content.created_at
        )
        for content in content_items
    ]
    
    return PaginatedResponse.create(
        items=content_summaries,
        total=total,
        pagination=pagination
    )


@router.get("/extracted-content/{content_id}", response_model=ExtractedContentResponse)
async def get_extracted_content(
    content_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get specific extracted content by ID."""
    content = _get_scoped_extracted_content(content_id, db, current_user)

    # Add computed fields
    content.mapped_sections_count = 0  # Would be computed with proper joins
    content.reviews_count = 0  # Would be computed with proper joins

    return content


@router.put("/extracted-content/{content_id}", response_model=ExtractedContentResponse)
async def update_extracted_content(
    content_id: UUID,
    content_update: ExtractedContentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update extracted content."""
    db_content = _get_scoped_extracted_content(content_id, db, current_user)
    
    # Update fields
    update_data = content_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_content, field, value)
    
    db.commit()
    db.refresh(db_content)
    
    # Add computed fields
    db_content.mapped_sections_count = 0
    db_content.reviews_count = 0
    
    return db_content


@router.get("/stats/extraction", response_model=ContentExtractionStats)
async def get_extraction_stats(
    project_id: Optional[UUID] = Query(None, description="Filter stats by project"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get content extraction statistics."""
    file_query = _scope_files(db.query(UploadedFile), current_user)
    content_query = _scope_extracted_content(db.query(ExtractedContent), current_user)

    if project_id:
        # Verify the requested project is in user's org (else returns no data)
        _assert_project_in_org(project_id, db, current_user)
        file_query = file_query.filter(UploadedFile.project_id == project_id)
        content_query = content_query.filter(UploadedFile.project_id == project_id)
    
    total_files = file_query.count()
    processed_files = file_query.filter(UploadedFile.is_processed == True).count()
    pending_files = total_files - processed_files
    
    total_extracted_items = content_query.count()
    reviewed_items = content_query.filter(ExtractedContent.reviewed == True).count()
    high_confidence_items = content_query.filter(ExtractedContent.confidence_score >= 0.8).count()
    
    extraction_accuracy = None
    if total_extracted_items > 0:
        extraction_accuracy = (high_confidence_items / total_extracted_items) * 100
    
    stats = ContentExtractionStats(
        total_files=total_files,
        processed_files=processed_files,
        pending_files=pending_files,
        total_extracted_items=total_extracted_items,
        reviewed_items=reviewed_items,
        high_confidence_items=high_confidence_items,
        extraction_accuracy=extraction_accuracy
    )
    
    return stats


@router.post("/batch/upload")
async def batch_upload_files(
    files: List[UploadFile] = File(...),
    project_id: UUID = Query(..., description="Project ID"),
    submission_id: Optional[UUID] = Query(None, description="Submission ID (optional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple files in batch."""
    # Verify project belongs to user's org
    _assert_project_in_org(project_id, db, current_user)

    # Verify submission exists if provided
    if submission_id:
        submission_query = db.query(Submission).filter(
            and_(
                Submission.id == submission_id,
                Submission.project_id == project_id,
            )
        )
        if not current_user.is_super_admin:
            submission_query = submission_query.filter(
                Submission.organization_id == current_user.organization_id
            )
        submission = submission_query.first()
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found or does not belong to the specified project"
            )
    
    # Process batch upload
    batch_service = FileBatchService(db)
    results = await batch_service.upload_multiple_files(files, project_id, submission_id)
    
    # Return frontend-compatible format
    return {
        "successful": results["successful"],
        "failed": results["failed"],
        "total_files": results["total_files"],
        "total_size": results["total_size"]
    }


@router.delete("/batch", response_model=FileBatchOperationResult)
async def batch_delete_files(
    batch_operation: FileBatchOperation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete multiple files in batch."""
    # Restrict the operation to files that belong to the user's org
    if not current_user.is_super_admin:
        allowed_ids = {
            row[0]
            for row in _scope_files(
                db.query(UploadedFile.id).filter(
                    UploadedFile.id.in_(batch_operation.file_ids)
                ),
                current_user,
            ).all()
        }
        scoped_file_ids = [fid for fid in batch_operation.file_ids if fid in allowed_ids]
    else:
        scoped_file_ids = list(batch_operation.file_ids)

    batch_service = FileBatchService(db)
    results = batch_service.delete_multiple_files(scoped_file_ids)

    return FileBatchOperationResult(
        successful_operations=[UUID(result["file_id"]) for result in results["successful"]],
        failed_operations=results["failed"],
        total_processed=results["total_files"],
        operation_summary=f"Batch delete completed: {len(results['successful'])} successful, {len(results['failed'])} failed"
    )


@router.get("/storage/stats", response_model=Dict[str, Any])
async def get_storage_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get file storage statistics. Super admins only."""
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Storage statistics are restricted to super administrators",
        )
    storage_service = FileStorageService()
    return storage_service.get_storage_stats()


@router.post("/validate", response_model=Dict[str, Any])
async def validate_file_upload(
    file: UploadFile = File(...),
    max_size_mb: Optional[int] = Query(None, description="Maximum file size in MB"),
    current_user: User = Depends(get_current_user),
):
    """Validate a file before upload without actually uploading it."""
    max_size = max_size_mb or settings.MAX_FILE_SIZE_MB
    validation_result = FileValidationService.validate_upload(file, max_size)
    
    return {
        "filename": file.filename,
        "size": file.size,
        "content_type": file.content_type,
        "validation": validation_result
    }