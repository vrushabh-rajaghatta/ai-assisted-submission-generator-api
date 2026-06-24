"""Pluggable storage backends for uploaded files.

Two backends are supported:

* ``LocalStorageBackend`` writes/reads files on the API host's filesystem,
  rooted at ``settings.UPLOAD_DIR``. This is the default and what dev uses.
* ``S3StorageBackend`` talks to any S3-compatible service (Supabase Storage,
  Cloudflare R2, AWS S3, MinIO, ...). Configured via the ``S3_*`` settings.

Both expose the same minimal interface so the rest of the app does not care
where bytes live. Object identity is an *object key* (a relative POSIX-style
path like ``projects/<uuid>/<file>.pdf``); the DB column
``uploaded_files.file_path`` stores this key.

For backward compatibility with rows written by older versions, the local
backend also accepts an absolute path stored in ``file_path`` and falls back
to using it directly.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator, Optional, Protocol

from app.core.config import settings


def derive_object_key(
    project_id: str,
    submission_id: Optional[str],
    stored_filename: str,
) -> str:
    """Return the canonical object key for a file.

    Mirrors the on-disk layout used by the local backend so files migrated
    between backends keep the same logical path.
    """
    if submission_id:
        return str(PurePosixPath("submissions") / str(submission_id) / stored_filename)
    return str(PurePosixPath("projects") / str(project_id) / stored_filename)


class StorageBackend(Protocol):
    """Common interface every storage backend must implement."""

    name: str

    def save_stream(self, key: str, source: BinaryIO) -> int:
        """Persist ``source`` at ``key`` and return the bytes written."""

    def open_stream(self, key: str) -> Iterator[bytes]:
        """Yield the object body in chunks (for streaming downloads)."""

    def exists(self, key: str) -> bool:
        """Return True if the object exists."""

    def delete(self, key: str) -> bool:
        """Delete the object. Returns True if something was removed."""

    def hash_object(self, key: str) -> Optional[str]:
        """Return SHA-256 of the stored bytes, or None if missing."""

    @contextlib.contextmanager
    def local_file(self, key: str) -> Iterator[Path]:
        """Yield a local ``Path`` pointing at the bytes for ``key``.

        For local storage this is the actual file. For remote backends the
        bytes are streamed into a temp file that is cleaned up on exit.
        """
        ...


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


class LocalStorageBackend:
    """Stores files under ``settings.UPLOAD_DIR``.

    Object keys are interpreted as POSIX-style relative paths beneath the
    upload root.
    """

    name = "local"

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or settings.UPLOAD_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("projects", "submissions", "temp", "processed"):
            (self.root / sub).mkdir(exist_ok=True)

    # -- helpers -------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        # Backward compat: if a legacy absolute path snuck into the DB,
        # honor it as long as it is inside the upload root.
        candidate = Path(key)
        if candidate.is_absolute():
            try:
                candidate.resolve().relative_to(self.root)
                return candidate
            except ValueError:
                # Outside the configured upload root: treat as untrusted and
                # reinterpret as a key under the root by stripping the prefix.
                key = candidate.name
                candidate = Path(key)
        path = (self.root / candidate).resolve()
        # Guard against path traversal via crafted keys.
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Object key escapes storage root: {key!r}") from exc
        return path

    # -- StorageBackend ------------------------------------------------------

    def save_stream(self, key: str, source: BinaryIO) -> int:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as out:
            shutil.copyfileobj(source, out)
        return target.stat().st_size

    def open_stream(self, key: str) -> Iterator[bytes]:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(key)
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    return
                yield chunk

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).exists()
        except ValueError:
            return False

    def delete(self, key: str) -> bool:
        try:
            path = self._resolve(key)
        except ValueError:
            return False
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def hash_object(self, key: str) -> Optional[str]:
        try:
            path = self._resolve(key)
        except ValueError:
            return None
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @contextlib.contextmanager
    def local_file(self, key: str) -> Iterator[Path]:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(key)
        yield path


# ---------------------------------------------------------------------------
# S3-compatible backend (Supabase, R2, S3, MinIO, ...)
# ---------------------------------------------------------------------------


class S3StorageBackend:
    """Talks to any S3-compatible API via boto3.

    Designed for Supabase Storage's S3 endpoint, Cloudflare R2, AWS S3, etc.
    Object keys are stored verbatim (no leading slash) and are the same shape
    as the local backend's relative paths.
    """

    name = "s3"

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        use_path_style: Optional[bool] = None,
    ) -> None:
        bucket = bucket or settings.S3_BUCKET
        if not bucket:
            raise RuntimeError(
                "S3 storage selected but S3_BUCKET is not configured."
            )

        # Imported lazily so local-only deployments don't have to install boto3.
        try:
            import boto3
            from botocore.client import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover - dependency check
            raise RuntimeError(
                "boto3 is required for S3 storage. Install it via "
                "`pip install boto3`."
            ) from exc

        self.bucket = bucket
        boto_config = BotoConfig(
            s3={
                "addressing_style": "path"
                if (settings.S3_USE_PATH_STYLE if use_path_style is None else use_path_style)
                else "virtual",
            },
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or settings.S3_ENDPOINT_URL,
            region_name=region or settings.S3_REGION,
            aws_access_key_id=access_key_id or settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=secret_access_key or settings.S3_SECRET_ACCESS_KEY,
            config=boto_config,
        )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _normalize_key(key: str) -> str:
        # Strip leading slashes; absolute paths are not valid object keys.
        return key.lstrip("/")

    # -- StorageBackend ------------------------------------------------------

    def save_stream(self, key: str, source: BinaryIO) -> int:
        key = self._normalize_key(key)
        # Read the stream into memory and use put_object for maximum
        # compatibility. Some S3-compatible services (notably Supabase
        # Storage's S3 endpoint) reject the multipart upload paths that
        # boto3's upload_fileobj triggers for larger files.
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass
        body = source.read()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)
        return len(body)

    def open_stream(self, key: str) -> Iterator[bytes]:
        key = self._normalize_key(key)
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc
        body = obj["Body"]
        try:
            for chunk in body.iter_chunks(chunk_size=64 * 1024):
                yield chunk
        finally:
            body.close()

    def exists(self, key: str) -> bool:
        key = self._normalize_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> bool:
        key = self._normalize_key(key)
        if not self.exists(key):
            return False
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True

    def hash_object(self, key: str) -> Optional[str]:
        # Most S3-compatible services do not expose a SHA-256 of the stored
        # bytes. We compute it on demand by streaming the object.
        if not self.exists(key):
            return None
        digest = hashlib.sha256()
        for chunk in self.open_stream(key):
            digest.update(chunk)
        return digest.hexdigest()

    @contextlib.contextmanager
    def local_file(self, key: str) -> Iterator[Path]:
        key = self._normalize_key(key)
        suffix = Path(key).suffix
        # delete=False so we can close the handle before yielding the path.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            for chunk in self.open_stream(key):
                tmp.write(chunk)
            tmp.flush()
            tmp.close()
            yield Path(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------


_BACKEND: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend (cached)."""
    global _BACKEND
    if _BACKEND is None:
        choice = (settings.STORAGE_BACKEND or "local").strip().lower()
        if choice == "s3":
            _BACKEND = S3StorageBackend()
        elif choice == "local":
            _BACKEND = LocalStorageBackend()
        else:
            raise RuntimeError(
                f"Unknown STORAGE_BACKEND={choice!r}; expected 'local' or 's3'."
            )
    return _BACKEND


def reset_storage_backend() -> None:
    """Drop the cached backend (used by tests / migration script)."""
    global _BACKEND
    _BACKEND = None
