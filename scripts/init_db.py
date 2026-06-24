#!/usr/bin/env python3
"""
Database initialization script.

This script creates all database tables and can be used for initial setup.
For production, use Alembic migrations instead.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.database import engine, Base
from app.core.config import settings
import app.models  # Import all models to register them


def create_tables():
    """Create all database tables."""
    print(f"Creating tables for database: {settings.DATABASE_URL}")
    print("Models registered:")
    for table_name in Base.metadata.tables.keys():
        print(f"  - {table_name}")
    
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created successfully!")


def drop_tables():
    """Drop all database tables."""
    print(f"Dropping tables for database: {settings.DATABASE_URL}")
    Base.metadata.drop_all(bind=engine)
    print("✅ All tables dropped successfully!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Database initialization script")
    parser.add_argument("--drop", action="store_true", help="Drop all tables before creating")
    parser.add_argument("--create", action="store_true", help="Create all tables")
    
    args = parser.parse_args()
    
    if args.drop:
        drop_tables()
    
    if args.create or not (args.drop):
        create_tables()
    
    if not args.drop and not args.create:
        print("Use --create to create tables or --drop to drop them")
        print("Example: python scripts/init_db.py --create")