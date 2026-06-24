#!/usr/bin/env python3
"""Bootstrap an organization and admin user (or a platform super admin).

Usage:
  # Regular org admin
  python scripts/bootstrap_admin.py \
      --org "Acme Health" --username acme_admin --password "<strong-pw>" --name "Acme Admin"

  # Platform super admin (lives in the auto-created '__platform__' org)
  python scripts/bootstrap_admin.py --super-admin \
      --username sadmin --password "<strong-pw>" --name "Platform Admin"

Safe to run multiple times: existing org/user with the same name/username are reused.
"""

import argparse
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.auth.models import Organization, User
from app.auth.seed import PLATFORM_ORG_NAME
from app.auth.services import hash_password
from app.core.database import SessionLocal
import app.models  # noqa: F401 -- register all models


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an organization + admin user, or a platform super admin")
    parser.add_argument("--super-admin", action="store_true", help="Create a platform-wide super admin (ignores --org)")
    parser.add_argument("--org", default=None, help="Organization name (required unless --super-admin)")
    parser.add_argument("--username", required=True, help="Admin username (any string)")
    parser.add_argument("--password", required=True, help="Admin password (min 8 chars)")
    parser.add_argument("--name", default=None, help="Admin full name")
    args = parser.parse_args()

    if len(args.password) < 8:
        raise SystemExit("Password must be at least 8 characters")

    org_name = PLATFORM_ORG_NAME if args.super_admin else args.org
    if not org_name:
        raise SystemExit("--org is required unless --super-admin is set")

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == org_name).first()
        if org is None:
            org = Organization(name=org_name, is_active=True)
            db.add(org)
            db.flush()
            print(f"Created organization: {org.name} ({org.id})")
        else:
            print(f"Organization already exists: {org.name} ({org.id})")

        username = args.username.strip().lower()
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                organization_id=org.id,
                username=username,
                hashed_password=hash_password(args.password),
                full_name=args.name,
                is_admin=True,
                is_super_admin=args.super_admin,
                is_active=True,
            )
            db.add(user)
            kind = "super admin" if args.super_admin else "admin"
            print(f"Created {kind} user: {user.username}")
        else:
            user.is_admin = True
            user.is_active = True
            user.hashed_password = hash_password(args.password)
            if args.super_admin:
                user.is_super_admin = True
            kind = "super admin" if args.super_admin else "admin"
            print(f"Updated existing {kind}: {user.username} (password reset)")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
