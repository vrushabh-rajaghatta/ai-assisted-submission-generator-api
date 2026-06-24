"""
File upload and storage services.
"""

import contextlib
import os
import uuid
import shutil
import mimetypes
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, BinaryIO, Iterator
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException, status
import hashlib
try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

from app.core.config import settings
from app.files.models import UploadedFile, FileType
from app.files.storage_backends import (
    LocalStorageBackend,
    derive_object_key,
    get_storage_backend,
)
from app.projects.models import Project
from app.submissions.models import Submission


class FileStorageService:
    """Service for handling file storage operations.

    Delegates the actual byte movement to a pluggable
    :class:`~app.files.storage_backends.StorageBackend` (local disk by
    default, S3-compatible when ``STORAGE_BACKEND=s3``).
    """

    def __init__(self):
        self.backend = get_storage_backend()
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.max_file_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024  # bytes

    def _get_file_type(self, filename: str, content_type: str) -> FileType:
        """Determine file type based on filename and content type."""
        filename_lower = filename.lower()

        # PDF files
        if filename_lower.endswith('.pdf'):
            return FileType.PDF

        # DOCX files
        elif filename_lower.endswith(('.docx', '.doc')):
            return FileType.DOCX

        # XLSX files
        elif filename_lower.endswith(('.xlsx', '.xls', '.csv')):
            return FileType.XLSX

        # Default to other
        else:
            return FileType.OTHER

    def _calculate_stream_hash_and_size(self, source: BinaryIO) -> tuple[str, int]:
        """Stream ``source`` once to compute its SHA-256 and total byte count.

        Resets the stream to the beginning so callers can re-read it.
        """
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        try:
            source.seek(0)
        except (AttributeError, OSError):
            # Some upload streams don't support seek; callers should pass a
            # file-like that does (UploadFile.file does on FastAPI's tempfile).
            pass
        return digest.hexdigest(), size

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent path traversal and other issues."""
        # Remove path components
        filename = os.path.basename(filename)

        # Replace problematic characters
        problematic_chars = '<>:"/\\|?*'
        for char in problematic_chars:
            filename = filename.replace(char, '_')

        # Limit length
        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[:255-len(ext)] + ext

        return filename

    async def save_uploaded_file(
        self,
        file: UploadFile,
        project_id: uuid.UUID,
        submission_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save an uploaded file and return file metadata."""

        # Validate file size
        if file.size and file.size > self.max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size ({file.size} bytes) exceeds maximum allowed size ({self.max_file_size} bytes)"
            )

        # Sanitize filename
        safe_filename = self._sanitize_filename(file.filename or "unknown")

        # Generate unique filename to prevent conflicts
        file_id = uuid.uuid4()
        _, ext = os.path.splitext(safe_filename)
        unique_filename = f"{file_id}{ext}"

        # Compute the object key (same shape across backends).
        object_key = derive_object_key(
            str(project_id),
            str(submission_id) if submission_id else None,
            unique_filename,
        )

        # Hash + size are computed before upload so we can keep them even
        # when the backend doesn't expose a stored-object hash (S3).
        try:
            file_hash, file_size = self._calculate_stream_hash_and_size(file.file)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading uploaded file: {exc}",
            )

        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )
        if file_size > self.max_file_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size ({file_size} bytes) exceeds maximum allowed size ({self.max_file_size} bytes)",
            )

        # Persist via the configured backend.
        try:
            self.backend.save_stream(object_key, file.file)
        except Exception as exc:
            # Best effort cleanup if a partial object was written.
            with contextlib.suppress(Exception):
                self.backend.delete(object_key)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error saving file to storage: {exc}",
            )

        # Detect MIME type. python-magic needs local bytes; if we are on a
        # remote backend we read the first 4 KB by streaming the source again.
        detected_mime_type = (
            file.content_type
            or mimetypes.guess_type(safe_filename)[0]
            or "application/octet-stream"
        )
        if HAS_MAGIC:
            try:
                with self.backend.local_file(object_key) as local_path:
                    detected_mime_type = magic.from_file(str(local_path), mime=True)
            except Exception:
                pass

        return {
            "file_id": file_id,
            "original_filename": safe_filename,
            "stored_filename": unique_filename,
            "file_path": object_key,
            "file_size": file_size,
            "file_hash": file_hash,
            "file_type": self._get_file_type(safe_filename, file.content_type or ""),
            "mime_type": detected_mime_type,
            "description": description,
        }

    # -- backend access helpers ------------------------------------------------

    def _object_key(self, file_record: UploadedFile) -> str:
        """Return the object key for a file record.

        Falls back to the legacy on-disk layout for rows whose ``file_path``
        was written before the storage backend was introduced.
        """
        stored = file_record.file_path or ""
        if stored:
            return stored
        return derive_object_key(
            str(file_record.project_id),
            str(file_record.submission_id) if file_record.submission_id else None,
            file_record.stored_filename,
        )

    def get_file_path(self, file_record: UploadedFile) -> Path:
        """Return a local filesystem path for a stored file.

        Only meaningful for the local backend. Callers that may run against
        S3 should use :meth:`local_file` instead.
        """
        if not isinstance(self.backend, LocalStorageBackend):
            raise RuntimeError(
                "get_file_path() is only supported with the local storage "
                "backend; use FileStorageService.local_file() instead."
            )
        return self.backend._resolve(self._object_key(file_record))

    @contextlib.contextmanager
    def local_file(self, file_record: UploadedFile) -> Iterator[Path]:
        """Yield a local Path for ``file_record`` regardless of backend.

        For the local backend this is the actual on-disk file. For remote
        backends the bytes are streamed into a temp file that is removed on
        exit, so callers must use this as a context manager.
        """
        with self.backend.local_file(self._object_key(file_record)) as path:
            yield path

    def open_stream(self, file_record: UploadedFile) -> Iterator[bytes]:
        """Yield the file bytes in chunks for streaming downloads."""
        return self.backend.open_stream(self._object_key(file_record))

    def delete_file(self, file_record: UploadedFile) -> bool:
        """Delete a file from storage."""
        try:
            return self.backend.delete(self._object_key(file_record))
        except Exception:
            return False

    def file_exists(self, file_record: UploadedFile) -> bool:
        """Whether the file's bytes are still in the storage backend."""
        try:
            return self.backend.exists(self._object_key(file_record))
        except Exception:
            return False

    def verify_file_integrity(self, file_record: UploadedFile) -> bool:
        """Verify file integrity using stored hash."""
        current_hash = self.backend.hash_object(self._object_key(file_record))
        if not current_hash:
            return False
        return current_hash == file_record.file_hash

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics.

        Cheap stats only for the local backend (walks the upload root). For
        the S3 backend we skip the walk to avoid LIST/HEAD costs and rely on
        the DB for aggregates.
        """
        stats: Dict[str, Any] = {
            "backend": self.backend.name,
            "total_files": 0,
            "total_size": 0,
            "by_type": {},
            "by_project": {},
            "storage_path": str(self.upload_dir),
        }

        if not isinstance(self.backend, LocalStorageBackend):
            return stats

        if not self.upload_dir.exists():
            return stats

        for file_path in self.upload_dir.rglob("*"):
            if file_path.is_file():
                stats["total_files"] += 1
                file_size = file_path.stat().st_size
                stats["total_size"] += file_size

                # Count by extension
                ext = file_path.suffix.lower()
                if ext not in stats["by_type"]:
                    stats["by_type"][ext] = {"count": 0, "size": 0}
                stats["by_type"][ext]["count"] += 1
                stats["by_type"][ext]["size"] += file_size

        return stats


class FileValidationService:
    """Service for validating uploaded files."""
    
    ALLOWED_EXTENSIONS = {
        'documents': {'.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt'},
        'images': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.svg', '.webp'},
        'spreadsheets': {'.xls', '.xlsx', '.csv', '.ods'},
        'presentations': {'.ppt', '.pptx', '.odp'},
        'archives': {'.zip', '.rar', '.7z', '.tar', '.gz'},
        'media': {'.mp4', '.avi', '.mov', '.wmv', '.mp3', '.wav'}
    }
    
    DANGEROUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.com', '.pif', '.scr', '.vbs', '.js'}
    
    @classmethod
    def validate_file_extension(cls, filename: str) -> Dict[str, Any]:
        """Validate file extension."""
        ext = Path(filename).suffix.lower()
        
        # Check for dangerous extensions
        if ext in cls.DANGEROUS_EXTENSIONS:
            return {
                "is_valid": False,
                "error": f"File type '{ext}' is not allowed for security reasons",
                "category": "security"
            }
        
        # Check if extension is in allowed list
        allowed = False
        category = "other"
        
        for cat, extensions in cls.ALLOWED_EXTENSIONS.items():
            if ext in extensions:
                allowed = True
                category = cat
                break
        
        if not allowed and ext:  # Allow files without extensions
            return {
                "is_valid": False,
                "error": f"File type '{ext}' is not supported",
                "category": "unsupported"
            }
        
        return {
            "is_valid": True,
            "category": category,
            "extension": ext
        }
    
    @classmethod
    def validate_file_content(cls, file_path: Path) -> Dict[str, Any]:
        """Validate file content (basic checks)."""
        try:
            # Check if file is readable
            with open(file_path, 'rb') as f:
                # Read first few bytes to check for common malicious patterns
                header = f.read(1024)
                
                # Basic checks for executable signatures
                if header.startswith(b'MZ'):  # Windows executable
                    return {
                        "is_valid": False,
                        "error": "File appears to be an executable",
                        "category": "security"
                    }
                
                # Check for script signatures
                if header.startswith(b'#!/') or b'<script' in header.lower():
                    return {
                        "is_valid": False,
                        "error": "File appears to contain executable script content",
                        "category": "security"
                    }
            
            return {"is_valid": True}
            
        except Exception as e:
            return {
                "is_valid": False,
                "error": f"Error reading file: {str(e)}",
                "category": "error"
            }
    
    @classmethod
    def validate_upload(cls, file: UploadFile, max_size_mb: int = 100) -> Dict[str, Any]:
        """Comprehensive validation of uploaded file."""
        errors = []
        warnings = []
        
        # Validate filename
        if not file.filename:
            errors.append("Filename is required")
        else:
            ext_validation = cls.validate_file_extension(file.filename)
            if not ext_validation["is_valid"]:
                errors.append(ext_validation["error"])
        
        # Validate file size
        if file.size:
            max_size_bytes = max_size_mb * 1024 * 1024
            if file.size > max_size_bytes:
                errors.append(f"File size ({file.size} bytes) exceeds maximum ({max_size_bytes} bytes)")
            elif file.size == 0:
                errors.append("File is empty")
        
        # Validate content type
        if file.content_type:
            suspicious_types = ['application/x-msdownload', 'application/x-executable']
            if file.content_type in suspicious_types:
                errors.append(f"Content type '{file.content_type}' is not allowed")
        
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }


class FileBatchService:
    """Service for handling batch file operations."""
    
    def __init__(self, db: Session):
        self.db = db
        self.storage_service = FileStorageService()
    
    async def upload_multiple_files(
        self,
        files: List[UploadFile],
        project_id: uuid.UUID,
        submission_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Upload multiple files in batch."""
        
        results = {
            "successful": [],
            "failed": [],
            "total_files": len(files),
            "total_size": 0
        }
        
        for file in files:
            try:
                # Validate file
                validation = FileValidationService.validate_upload(file, settings.MAX_FILE_SIZE_MB)
                if not validation["is_valid"]:
                    results["failed"].append({
                        "filename": file.filename,
                        "errors": validation["errors"]
                    })
                    continue
                
                # Save file
                file_metadata = await self.storage_service.save_uploaded_file(
                    file, project_id, submission_id
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
                    file_hash=file_metadata["file_hash"]
                )
                
                self.db.add(db_file)
                results["successful"].append({
                    "filename": file.filename,
                    "file_id": str(file_metadata["file_id"]),
                    "size": file_metadata["file_size"]
                })
                results["total_size"] += file_metadata["file_size"]
                
            except Exception as e:
                results["failed"].append({
                    "filename": file.filename,
                    "error": str(e)
                })
        
        # Commit all successful uploads
        if results["successful"]:
            self.db.commit()
        
        return results
    
    def delete_multiple_files(self, file_ids: List[uuid.UUID]) -> Dict[str, Any]:
        """Delete multiple files in batch."""
        
        results = {
            "successful": [],
            "failed": [],
            "total_files": len(file_ids)
        }
        
        for file_id in file_ids:
            try:
                # Get file record
                file_record = self.db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
                if not file_record:
                    results["failed"].append({
                        "file_id": str(file_id),
                        "error": "File not found in database"
                    })
                    continue
                
                # Delete from storage
                if self.storage_service.delete_file(file_record):
                    # Delete from database
                    self.db.delete(file_record)
                    results["successful"].append({
                        "file_id": str(file_id),
                        "filename": file_record.original_filename
                    })
                else:
                    results["failed"].append({
                        "file_id": str(file_id),
                        "error": "Failed to delete file from storage"
                    })
                    
            except Exception as e:
                results["failed"].append({
                    "file_id": str(file_id),
                    "error": str(e)
                })
        
        # Commit deletions
        if results["successful"]:
            self.db.commit()
        
        return results