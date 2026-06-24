"""Seed platform super admins from a JSON file at startup.

The seed file is opt-in: pass its path via `AUTH_SEED_FILE` env var (defaults to
`./seed_admin_creds.json` in the working directory). If the file does not exist,
seeding is silently skipped.

Schema (JSON):
{
  "super_admins": [
    {"username": "sadmin", "password": "<strong>", "full_name": "Platform Admin"}
  ]
}

Behavior:
- Only super admins are seeded. All other organizations and users are created
  by a super admin at runtime via /api/auth/super-admin/* (and the Admin page
  in the UI).
- Super admins live in an auto-created `__platform__` organization. They have
  `is_super_admin=True` and `is_admin=True`.
- Usernames are normalized to lowercase. They can be anything: "sadmin",
  "admin@company1.com", etc.
- If a user already exists, their password is NOT overwritten (so rotating the
  seed file does not silently reset passwords). To force-reset, set
  "force_reset_password": true on the user entry.
- After seeding, a banner is printed to stdout listing every super admin.
  Passwords are NEVER printed unless you opt in via env var
  SEED_PRINT_PASSWORDS=1 (local-dev only).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.auth.models import Organization, User
from app.auth.services import hash_password
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

PLATFORM_ORG_NAME = "__platform__"


@dataclass
class _SeedResult:
    platform_org_created: bool = False
    admins: list[dict[str, Any]] = field(default_factory=list)


def _resolve_seed_path() -> str:
    return os.environ.get("AUTH_SEED_FILE", "./seed_admin_creds.json")


def _get_or_create_platform_org(db: Session) -> tuple[Organization, bool]:
    org = db.query(Organization).filter(Organization.name == PLATFORM_ORG_NAME).first()
    if org is not None:
        return org, False
    org = Organization(name=PLATFORM_ORG_NAME, is_active=True)
    db.add(org)
    db.flush()
    return org, True


def _seed_super_admins(db: Session, super_specs: list[dict[str, Any]]) -> _SeedResult:
    result = _SeedResult()
    if not super_specs:
        return result

    org, created_org = _get_or_create_platform_org(db)
    result.platform_org_created = created_org
    if created_org:
        logger.info("Auth seed: created platform org '%s'", PLATFORM_ORG_NAME)

    for admin_spec in super_specs:
        username = (admin_spec.get("username") or admin_spec.get("email") or "").strip().lower()
        password = admin_spec.get("password")
        if not username or not password:
            logger.warning("Auth seed: skipping super admin (missing username/password)")
            continue
        if len(password) < 8:
            logger.warning("Auth seed: skipping super admin '%s' (password too short)", username)
            continue

        existing = db.query(User).filter(User.username == username).first()
        if existing is None:
            db.add(User(
                organization_id=org.id,
                username=username,
                hashed_password=hash_password(password),
                full_name=admin_spec.get("full_name"),
                is_admin=True,
                is_super_admin=True,
                is_active=True,
            ))
            status = "created"
            logger.info("Auth seed: created super admin '%s'", username)
        elif admin_spec.get("force_reset_password"):
            existing.hashed_password = hash_password(password)
            existing.is_active = True
            existing.is_admin = True
            existing.is_super_admin = True
            status = "reset"
            logger.info("Auth seed: reset password for super admin '%s'", username)
        else:
            if not existing.is_super_admin:
                existing.is_super_admin = True
                existing.is_admin = True
                logger.info("Auth seed: promoted '%s' to super admin", username)
            status = "existing"

        result.admins.append({
            "username": username,
            "full_name": admin_spec.get("full_name"),
            "status": status,
            "password": password,
        })

    return result


def _print_banner(result: _SeedResult) -> None:
    if not result.admins:
        return

    print_passwords = os.environ.get("SEED_PRINT_PASSWORDS", "").lower() in {"1", "true", "yes"}
    bar = "=" * 72

    lines = ["", bar, "  Auth seed summary (super admins)"]
    if print_passwords:
        lines.append("  WARNING: SEED_PRINT_PASSWORDS=1 -- passwords printed below.")
    lines.append(bar)

    org_prefix = "[NEW]" if result.platform_org_created else "[OK ]"
    lines.append(f"  {org_prefix} platform org: {PLATFORM_ORG_NAME}")

    for admin in result.admins:
        status_label = {
            "created": "created",
            "reset": "password reset",
            "existing": "already existed",
        }.get(admin["status"], admin["status"])
        display = admin["username"]
        if admin.get("full_name"):
            display = f"{admin['full_name']} <{admin['username']}>"
        line = f"        - {display} [super]  [{status_label}]"
        if print_passwords:
            line += f"  password={admin['password']!r}"
        lines.append(line)

    lines.append(bar)
    if not print_passwords:
        lines.append("  Passwords live in your seed_admin_creds.json file (gitignored).")
        lines.append("  To print them here for local dev only, run with SEED_PRINT_PASSWORDS=1.")
        lines.append(bar)
    lines.append("  Create organizations and org admins via the Admin page (super admin only).")
    lines.append(bar)
    lines.append("")

    print("\n".join(lines), flush=True)


def seed_from_file() -> None:
    """Read the seed file (if any) and create super admin users."""
    path = _resolve_seed_path()
    if not os.path.exists(path):
        logger.debug("Auth seed: no file at %s, skipping", path)
        return

    try:
        with open(path, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Auth seed: failed to read %s: %s", path, exc)
        return

    super_admins = spec.get("super_admins") or []
    if not super_admins:
        logger.info("Auth seed: file %s contains no super_admins; nothing to do", path)
        if spec.get("organizations"):
            logger.warning(
                "Auth seed: file %s has 'organizations' entries but seeding now only "
                "handles 'super_admins'. Create organizations via the Admin UI or "
                "/api/auth/super-admin/* endpoints.",
                path,
            )
        return

    db = SessionLocal()
    try:
        result = _seed_super_admins(db, super_admins)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Auth seed: failed, rolled back")
        return
    finally:
        db.close()

    _print_banner(result)
