"""
AI service API router for document processing and content extraction.
"""

import os
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.core.config import settings
from app.ai.services import AIProcessingService
from app.ai.models import (
    AIProcessingRequest,
    AIProcessingResponse,
    ContentSuggestion
)
from app.ai.document_parser import document_parser
from app.ai.sarvam_service import sarvam_ai_service
from app.files.models import UploadedFile
from app.files.services import FileStorageService
from app.projects.models import Project
from app.submissions.models import Submission
from app.dossier.models import DossierSection
from app.dossier.services import is_leaf_section

router = APIRouter()


def _assert_submission_in_org(submission_id: UUID, db: Session, current_user: User) -> Submission:
    """Fetch submission and 404 if not in user's org."""
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


def _assert_file_in_org(file_id: UUID, db: Session, current_user: User) -> UploadedFile:
    """Fetch file and 404 if its project isn't in user's org."""
    file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
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


def _assert_section_in_org(section_id: UUID, db: Session, current_user: User) -> DossierSection:
    """Fetch dossier section and 404 if its submission isn't in user's org."""
    section = db.query(DossierSection).filter(DossierSection.id == section_id).first()
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


@router.post("/process-file", response_model=AIProcessingResponse)
async def process_file_with_ai(
    request: AIProcessingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Process an uploaded file with AI to extract content for dossier sections."""

    try:
        _assert_file_in_org(request.file_id, db, current_user)
        _assert_submission_in_org(request.submission_id, db, current_user)

        ai_service = AIProcessingService(db)
        result = ai_service.process_uploaded_file(
            file_id=request.file_id,
            submission_id=request.submission_id,
            auto_populate=request.processing_options.get("auto_populate", True)
        )
        
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI processing failed: {str(e)}"
        )


@router.get("/suggestions/{section_id}", response_model=List[ContentSuggestion])
async def get_section_content_suggestions(
    section_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI content suggestions for a specific dossier section."""

    try:
        _assert_section_in_org(section_id, db, current_user)
        ai_service = AIProcessingService(db)
        suggestions = ai_service.get_content_suggestions(section_id)
        
        return suggestions
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get content suggestions: {str(e)}"
        )


@router.get("/analyze-submission/{submission_id}")
async def analyze_submission_completeness(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze the completeness of a submission using AI insights."""

    try:
        _assert_submission_in_org(submission_id, db, current_user)
        ai_service = AIProcessingService(db)
        analysis = ai_service.analyze_submission_completeness(submission_id)
        
        return {
            "submission_id": str(submission_id),
            "analysis": analysis,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze submission: {str(e)}"
        )


@router.post("/auto-populate/{submission_id}")
async def auto_populate_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Process every uploaded file for a submission and populate AI-extracted content.

    This runs synchronously: the HTTP response only returns once every file has
    been processed. Expect this to take a while on submissions with many files
    (each file fans out one Sarvam call per leaf section).
    """

    _assert_submission_in_org(submission_id, db, current_user)

    submission = _assert_submission_in_org(submission_id, db, current_user)

    # Primary source: files explicitly linked to this submission.
    files = db.query(UploadedFile).filter(
        UploadedFile.submission_id == submission_id
    ).all()
    file_source = "submission"

    # Fallback: if no submission-linked files, try unlinked files for the same
    # product. These are files uploaded at product level without a submission.
    if not files:
        files = db.query(UploadedFile).filter(
            UploadedFile.product_id == submission.product_id,
            UploadedFile.submission_id.is_(None),
        ).all()
        file_source = "product_unlinked"

    if not files:
        return {
            "message": (
                "No documents found for this submission. "
                "No unlinked product documents were found either. "
                "Please upload files first."
            ),
            "file_source": "none",
            "files_processed": 0,
            "sections_updated": 0,
            "updated_section_ids": [],
            "errors": [],
        }

    ai_service = AIProcessingService(db)
    updated_section_ids: set[str] = set()
    files_processed = 0
    errors: list[dict[str, str]] = []

    for file_record in files:
        try:
            response = ai_service.process_uploaded_file(
                file_id=file_record.id,
                submission_id=submission_id,
                auto_populate=True,
            )
            if response.extraction_result.success:
                files_processed += 1
                for sid in response.sections_updated or []:
                    updated_section_ids.add(str(sid))
            else:
                errors.append({
                    "filename": file_record.original_filename,
                    "error": response.extraction_result.error_message or "extraction failed",
                })
        except Exception as e:  # noqa: BLE001 — surface per-file errors, keep going
            errors.append({
                "filename": file_record.original_filename,
                "error": str(e),
            })

    return {
        "message": (
            f"Auto-population completed: {len(updated_section_ids)} sections updated "
            f"from {files_processed}/{len(files)} files"
            + (
                " (using unlinked product files fallback)"
                if file_source == "product_unlinked"
                else ""
            )
        ),
        "file_source": file_source,
        "files_processed": files_processed,
        "total_files": len(files),
        "sections_updated": len(updated_section_ids),
        "updated_section_ids": sorted(updated_section_ids),
        "errors": errors,
    }


@router.get("/stats")
async def get_ai_processing_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get AI processing statistics. Super admins only (cross-org aggregate)."""

    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI processing statistics are restricted to super administrators",
        )

    try:
        ai_service = AIProcessingService(db)
        stats = ai_service.get_processing_stats()
        
        return {
            "ai_processing_stats": stats,
            "timestamp": time.time()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get AI stats: {str(e)}"
        )


@router.post("/extract-text/{file_id}")
async def extract_text_from_file(
    file_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract raw text content from an uploaded file."""

    try:
        # Get file record (org-scoped)
        file_record = _assert_file_in_org(file_id, db, current_user)

        storage_service = FileStorageService()
        if not storage_service.file_exists(file_record):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in storage",
            )

        with storage_service.local_file(file_record) as local_path:
            file_path = str(local_path)
            document_content = document_parser.parse_document(
                file_path, file_record.mime_type
            )
            can_process = document_parser.can_parse(file_path)

        return {
            "file_id": str(file_id),
            "filename": file_record.original_filename,
            "extracted_content": document_content.dict(),
            "can_process": can_process,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text extraction failed: {str(e)}"
        )


@router.post("/generate-section-content/{section_id}")
async def generate_section_content_with_ai(
    section_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate content for a section using Sarvam AI.

    If the section's submission has uploaded documents, extract content grounded in
    those documents (single Sarvam call scoped to this one section). Otherwise fall
    back to template-only generation from section requirements.
    """

    try:
        section = _assert_section_in_org(section_id, db, current_user)

        if not is_leaf_section(db, section_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Only leaf sections can be generated. "
                    f"Section {section.section_code} has child sections — "
                    "generate content for those instead."
                ),
            )

        if not sarvam_ai_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sarvam AI service not configured. Please set SARVAM_API_KEY environment variable."
            )

        from app.ai.content_mapper import content_mapper
        requirements = content_mapper.get_section_requirements(section.section_code)

        # Gather any uploaded documents for this submission and use them as grounding
        combined_text = ""
        processed_files: list[str] = []
        skipped_files: list[str] = []

        files = db.query(UploadedFile).filter(
            UploadedFile.submission_id == section.submission_id
        ).all()

        storage_service = FileStorageService()
        for file_record in files:
            try:
                with storage_service.local_file(file_record) as local_path:
                    if not document_parser.can_parse(str(local_path)):
                        skipped_files.append(file_record.original_filename)
                        continue
                    doc_content = document_parser.parse_document(
                        str(local_path), file_record.mime_type
                    )
                if doc_content and doc_content.text and doc_content.text.strip():
                    combined_text += f"\n\n--- {file_record.original_filename} ---\n"
                    combined_text += doc_content.text
                    processed_files.append(file_record.original_filename)
                else:
                    skipped_files.append(file_record.original_filename)
            except FileNotFoundError:
                skipped_files.append(
                    f"{file_record.original_filename} (missing in storage)"
                )
            except Exception as parse_err:  # noqa: BLE001 — surfaced via skipped list
                skipped_files.append(f"{file_record.original_filename} (parse error: {parse_err})")

        generated_content: str = ""
        confidence_score: float | None = None
        source: str

        if combined_text.strip():
            mapping = sarvam_ai_service.extract_section_content(
                combined_text, section, requirements
            )
            if mapping and mapping.extracted_content:
                generated_content = mapping.extracted_content
                confidence_score = mapping.confidence_score
                source = "documents"
            else:
                # Extraction returned nothing usable — fall back to template
                generated_content = sarvam_ai_service.generate_section_content(
                    section, requirements
                )
                source = "template_fallback"
        else:
            generated_content = sarvam_ai_service.generate_section_content(
                section, requirements
            )
            source = "template"

        return {
            "section_id": str(section_id),
            "section_code": section.section_code,
            "section_title": section.section_title,
            "generated_content": generated_content,
            "requirements": requirements,
            "ai_model": settings.SARVAM_MODEL,
            "source": source,
            "processed_files": processed_files,
            "skipped_files": skipped_files,
            "confidence_score": confidence_score,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Content generation failed: {str(e)}"
        )


@router.post("/analyze-document-completeness/{submission_id}")
async def analyze_document_completeness_with_ai(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze document completeness using Sarvam AI."""

    try:
        _assert_submission_in_org(submission_id, db, current_user)

        if not sarvam_ai_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sarvam AI service not configured"
            )
        
        # Get all files for this submission
        files = db.query(UploadedFile).filter(
            UploadedFile.submission_id == submission_id
        ).all()
        
        if not files:
            return {
                "message": "No files found for analysis",
                "analysis": {"coverage_score": 0.0, "recommendations": ["Upload documents for analysis"]}
            }
        
        # Get dossier sections
        sections = db.query(DossierSection).filter(
            DossierSection.submission_id == submission_id
        ).all()
        
        # Combine all document text
        combined_text = ""
        processed_files = []

        storage_service = FileStorageService()
        for file_record in files:
            try:
                with storage_service.local_file(file_record) as local_path:
                    if document_parser.can_parse(str(local_path)):
                        doc_content = document_parser.parse_document(str(local_path))
                        combined_text += f"\n\n--- {file_record.original_filename} ---\n"
                        combined_text += doc_content.text
                        processed_files.append(file_record.original_filename)
            except Exception as e:
                print(f"Error processing file {file_record.original_filename}: {e}")
        
        if not combined_text.strip():
            return {
                "message": "No readable content found in uploaded files",
                "analysis": {"coverage_score": 0.0, "recommendations": ["Upload readable documents (PDF, DOCX, TXT)"]}
            }
        
        # Analyze with Sarvam AI
        analysis = sarvam_ai_service.analyze_document_completeness(
            combined_text, 
            sections
        )
        
        return {
            "submission_id": str(submission_id),
            "processed_files": processed_files,
            "analysis": analysis,
            "ai_model": settings.SARVAM_MODEL
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document analysis failed: {str(e)}"
        )


@router.get("/ai-status")
async def get_ai_service_status():
    """Get the status of AI services."""
    
    return {
        "sarvam_ai_available": sarvam_ai_service is not None,
        "sarvam_api_key_configured": bool(settings.SARVAM_API_KEY),
        "supported_models": [
            settings.SARVAM_MODEL,
        ] if sarvam_ai_service else [],
        "fallback_method": "keyword_matching" if not sarvam_ai_service else None
    }


@router.get("/conflicts/{submission_id}")
async def get_submission_conflicts(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all sections with conflicts for a submission."""
    try:
        _assert_submission_in_org(submission_id, db, current_user)

        # Get all sections with conflicts
        conflicted_sections = db.query(DossierSection).filter(
            DossierSection.submission_id == submission_id,
            DossierSection.has_conflicts == True
        ).all()
        
        conflicts = []
        for section in conflicted_sections:
            # Get source file info
            source_file = None
            if section.source_file_id:
                source_file = db.query(UploadedFile).filter(
                    UploadedFile.id == section.source_file_id
                ).first()
            
            conflict_data = {
                "section_id": str(section.id),
                "section_code": section.section_code,
                "section_title": section.section_title,
                "current_content": section.content,
                "ai_extracted_content": section.ai_extracted_content,
                "ai_confidence_score": section.ai_confidence_score,
                "source_file": {
                    "id": str(source_file.id),
                    "filename": source_file.original_filename
                } if source_file else None,
                "conflict_sources": section.conflict_sources or [],
                "conflict_count": len(section.conflict_sources or [])
            }
            conflicts.append(conflict_data)
        
        return {
            "submission_id": str(submission_id),
            "conflicts": conflicts,
            "total_conflicts": len(conflicts)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conflicts: {str(e)}"
        )


@router.post("/resolve-conflict/{section_id}")
async def resolve_section_conflict(
    section_id: UUID,
    resolution: dict,  # {"action": "keep_current|use_alternative", "content": "selected_content"}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve a conflict for a specific section."""
    try:
        section = _assert_section_in_org(section_id, db, current_user)
        
        action = resolution.get("action")
        selected_content = resolution.get("content", "")
        
        if action == "keep_current":
            # Keep current content, clear conflicts
            section.has_conflicts = False
            section.conflict_sources = None
        elif action == "use_alternative":
            # Use selected alternative content
            section.content = selected_content
            section.has_conflicts = False
            section.conflict_sources = None
            section.completion_percentage = min(section.completion_percentage, 90)  # Human-reviewed
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid resolution action"
            )
        
        db.commit()
        
        return {
            "message": "Conflict resolved successfully",
            "section_id": str(section_id),
            "action": action,
            "resolved_content": section.content
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve conflict: {str(e)}"
        )