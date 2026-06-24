"""
Main FastAPI application entry point.
"""

import logging
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.auth.dependencies import get_current_user
import app.models  # Import all models to register them
from app.auth.router import router as auth_router
from app.projects.router import router as projects_router
from app.products.router import router as products_router
from app.submissions.router import router as submissions_router
from app.dossier.router import router as dossier_router
from app.files.router import router as files_router
from app.ai.router import router as ai_router
from app.reviews.router import router as reviews_router
from app.validation.router import router as validation_router
from app.dashboard.router import router as dashboard_router


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    # AI logging is configured in logging_utils.py to write to logs.txt
    
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="AI-Assisted Regulatory Submission Builder API",
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth router has no auth dependency (login is public; protected endpoints inside
    # the router add their own dependency).
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

    # All other routers require an authenticated user.
    protected_route_dependencies = [Depends(get_current_user)]
    app.include_router(
        projects_router,
        prefix="/api/projects",
        tags=["projects"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        products_router,
        prefix="/api/products",
        tags=["products"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        submissions_router,
        prefix="/api/submissions",
        tags=["submissions"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        dossier_router,
        prefix="/api/dossier",
        tags=["dossier"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        files_router,
        prefix="/api/files",
        tags=["files"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        ai_router,
        prefix="/api/ai",
        tags=["ai"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        reviews_router,
        prefix="/api/reviews",
        tags=["reviews"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        validation_router,
        prefix="/api/validation",
        tags=["validation"],
        dependencies=protected_route_dependencies,
    )
    app.include_router(
        dashboard_router,
        prefix="/api/dashboard",
        tags=["dashboard"],
        dependencies=protected_route_dependencies,
    )

    # Static file serving for uploads
    if settings.SERVE_UPLOADS_PUBLIC and os.path.exists(settings.UPLOAD_DIR):
        app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

    return app


# Create the application instance
app = create_application()


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    # Create upload directory if it doesn't exist
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.TEMPLATES_DIR, exist_ok=True)

    # Seed organizations / admin users from seed_admin_creds.json if present
    from app.auth.seed import seed_from_file
    seed_from_file()
    
    # Log application startup
    from app.ai.logging_utils import AILogger
    AILogger.log_simple_call(
        function_name="application_startup",
        model="system",
        duration=0,
        success=True,
        additional_data={
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "upload_dir": settings.UPLOAD_DIR,
            "templates_dir": settings.TEMPLATES_DIR
        }
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.APP_VERSION}