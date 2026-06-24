# AI-Assisted Regulatory Submission Builder - Backend

A FastAPI-based backend for building regulatory submission dossiers for Health Canada medical device submissions using IMDRF templates.

## Architecture

This application follows a **modular monolith** architecture with clean separation of concerns:

### Core Modules

- **`/core`** - Configuration, database setup, security utilities
- **`/projects`** - Project management and client association
- **`/products`** - Medical device product metadata management
- **`/submissions`** - Regulatory submission lifecycle management
- **`/dossier`** - IMDRF template loading and dossier structure building
- **`/files`** - File upload and storage management
- **`/ai`** - AI content extraction services (mock implementation)
- **`/reviews`** - Human review workflow and approval process
- **`/validation`** - Data consistency checks and validation guardrails

## Key Features

- **Human-in-the-loop workflow** with approval gates
- **IMDRF template support** with hierarchical section management
- **File upload system** for PDF/DOCX/XLSX documents
- **Mock AI extraction** ready for future integration
- **Comprehensive validation** and consistency checking
- **REST API** with proper status codes and error handling

## Technology Stack

- **FastAPI** - Modern Python web framework
- **SQLAlchemy** - ORM with PostgreSQL
- **Pydantic** - Data validation and serialization
- **Alembic** - Database migrations
- **PostgreSQL** - Primary database

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your database credentials
   ```

3. Run database migrations:
   ```bash
   alembic upgrade head
   ```

4. Start the development server:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## API Documentation

When running in debug mode, API documentation is available at:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Project Structure

```
backend/
├── app/
│   ├── core/           # Configuration and database setup
│   ├── projects/       # Project management
│   ├── products/       # Product metadata
│   ├── submissions/    # Submission lifecycle
│   ├── dossier/        # IMDRF templates and structure
│   ├── files/          # File upload and storage
│   ├── ai/             # AI extraction services
│   ├── reviews/        # Human review workflow
│   ├── validation/     # Consistency checks
│   └── main.py         # FastAPI application entry point
├── templates/          # IMDRF template JSON files
├── uploads/            # Local file storage
├── requirements.txt    # Python dependencies
└── .env.example        # Environment configuration template
```

## Database Schema

The application uses the following main entities:
- **Projects** - Top-level regulatory projects
- **Products** - Medical devices within projects
- **Submissions** - Regulatory submissions with status tracking
- **Dossier Sections** - Hierarchical IMDRF template structure
- **Files** - Uploaded documents with metadata
- **Extracted Content** - AI-extracted content snippets
- **Reviews** - Human review records and decisions
- **Validation Alerts** - Consistency and completeness checks