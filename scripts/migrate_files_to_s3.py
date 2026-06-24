"""Migrate existing local-disk uploads to the configured S3 backend.

Run this once after setting up your S3-compatible bucket (Supabase, R2, etc.)
and before flipping ``STORAGE_BACKEND=s3`` in production.

Usage::

    # Dry run (default) - shows what would be migrated without uploading.
    python scripts/migrate_files_to_s3.py

    # Actually upload to S3 and rewrite the DB rows to point at object keys.
    python scripts/migrate_files_to_s3.py --apply

    # Also delete the local file after a successful upload.
    python scripts/migrate_files_to_s3.py --apply --delete-local

The script is idempotent:
- Rows whose ``file_path`` is already an object key (no leading ``/``,
  no host-specific prefix) are left alone unless ``--reupload`` is passed.
- A SHA-256 check is performed after upload; mismatches fail the row and
  do not rewrite the DB.

Environment expectations:
- The S3 settings (``S3_ENDPOINT_URL``, ``S3_BUCKET``, ``S3_ACCESS_KEY_ID``,
  ``S3_SECRET_ACCESS_KEY``, ``S3_REGION``) must be configured even if
  ``STORAGE_BACKEND`` is still ``local`` in your runtime ``.env``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Allow running from the repo root (``python scripts/migrate_files_to_s3.py``)
# without installing the package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.files.models import UploadedFile  # noqa: E402
from app.files.storage_backends import (  # noqa: E402
    LocalStorageBackend,
    S3StorageBackend,
    derive_object_key,
)


def _looks_like_object_key(value: str) -> bool:
    """Return True for paths that look like S3 keys, not absolute file paths."""
    if not value:
        return False
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        return False
    return True


def _resolve_local_path(file_path: str, stored_filename: str, project_id: str,
                       submission_id: str | None, local_root: Path) -> Path | None:
    """Find the on-disk file for a row, accommodating legacy storage layouts."""
    candidates = []
    raw = Path(file_path) if file_path else None
    if raw is not None:
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append((local_root / raw).resolve())

    canonical = local_root / derive_object_key(project_id, submission_id, stored_filename)
    candidates.append(canonical)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform uploads and DB rewrites. Without this, dry-run only.",
    )
    parser.add_argument(
        "--delete-local",
        action="store_true",
        help="Delete the local file after a successful upload (only with --apply).",
    )
    parser.add_argument(
        "--reupload",
        action="store_true",
        help="Re-upload rows whose file_path already looks like an object key.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of rows to process (0 = all).",
    )
    args = parser.parse_args()

    if not settings.S3_BUCKET:
        print("ERROR: S3_BUCKET is not configured. Aborting.", file=sys.stderr)
        return 2

    backend = S3StorageBackend()
    local_root = Path(settings.UPLOAD_DIR).resolve()

    if not local_root.exists():
        print(f"WARNING: UPLOAD_DIR {local_root} does not exist; nothing to migrate.")

    db = SessionLocal()
    try:
        query = db.query(UploadedFile).order_by(UploadedFile.created_at.asc())
        if args.limit > 0:
            query = query.limit(args.limit)
        rows = query.all()
        total = len(rows)
        print(
            f"Found {total} uploaded_files row(s). "
            f"Mode: {'APPLY' if args.apply else 'DRY RUN'} | "
            f"Bucket: {settings.S3_BUCKET}"
        )

        migrated = 0
        skipped_already_key = 0
        skipped_missing = 0
        failed = 0

        for index, row in enumerate(rows, start=1):
            file_path_str = row.file_path or ""
            object_key = derive_object_key(
                str(row.project_id),
                str(row.submission_id) if row.submission_id else None,
                row.stored_filename,
            )

            if not args.reupload and _looks_like_object_key(file_path_str) and not Path(file_path_str).is_absolute():
                # Already migrated.
                skipped_already_key += 1
                continue

            local_path = _resolve_local_path(
                file_path_str,
                row.stored_filename,
                str(row.project_id),
                str(row.submission_id) if row.submission_id else None,
                local_root,
            )
            if local_path is None:
                print(f"  [{index}/{total}] MISSING  {row.id}  ({row.original_filename})")
                skipped_missing += 1
                continue

            local_size = local_path.stat().st_size
            print(
                f"  [{index}/{total}] {'UPLOAD ' if args.apply else 'WOULD  '} "
                f"{row.id}  {local_path}  -> s3://{settings.S3_BUCKET}/{object_key} "
                f"({local_size} bytes)"
            )

            if not args.apply:
                continue

            try:
                with open(local_path, "rb") as fh:
                    backend.save_stream(object_key, fh)

                # Verify byte-for-byte parity using SHA-256.
                local_hash = _hash_file(local_path)
                remote_hash = backend.hash_object(object_key)
                if local_hash != remote_hash:
                    print(
                        f"      FAIL hash mismatch (local={local_hash[:12]}, "
                        f"remote={remote_hash[:12] if remote_hash else 'none'})"
                    )
                    backend.delete(object_key)
                    failed += 1
                    continue

                row.file_path = object_key
                if not row.file_hash:
                    row.file_hash = local_hash
                db.commit()

                if args.delete_local:
                    try:
                        local_path.unlink()
                    except OSError as exc:
                        print(f"      WARN could not delete local file: {exc}")

                migrated += 1
            except Exception as exc:  # noqa: BLE001 - we want to keep going
                db.rollback()
                print(f"      FAIL {exc}")
                failed += 1

        print()
        print("Summary:")
        print(f"  total rows           : {total}")
        print(f"  migrated             : {migrated}")
        print(f"  already had key      : {skipped_already_key}")
        print(f"  missing on disk      : {skipped_missing}")
        print(f"  failed               : {failed}")
        if not args.apply:
            print("Dry run only. Re-run with --apply to perform the migration.")
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
