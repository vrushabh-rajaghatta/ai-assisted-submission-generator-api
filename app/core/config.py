"""
Application configuration using Pydantic settings.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "AI-Assisted Regulatory Submission Builder"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    
    # Database
    DATABASE_URL: str = "postgresql://username:password@localhost:5432/regulatory_submissions"
    
    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 100

    # Storage backend: "local" keeps files on disk under UPLOAD_DIR.
    # "s3" uses any S3-compatible service (Supabase Storage, Cloudflare R2,
    # MinIO, AWS S3, etc.) configured via S3_* settings below.
    STORAGE_BACKEND: str = "local"
    S3_ENDPOINT_URL: Optional[str] = None
    S3_REGION: str = "us-east-1"
    S3_BUCKET: Optional[str] = None
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None
    # Force path-style addressing (required for Supabase, MinIO, some R2 setups).
    S3_USE_PATH_STYLE: bool = True
    
    # IMDRF Templates
    TEMPLATES_DIR: str = "./templates/imdrf"
    
    # Logging
    LOG_LEVEL: str = "INFO"

    # Security
    CORS_ALLOWED_ORIGINS: str = "https://expert-telegram-wvvj4jx5q6529g9-3030.app.github.dev"
    SERVE_UPLOADS_PUBLIC: bool = False
    INTERNAL_API_KEY: Optional[str] = None

    # JWT / auth
    JWT_SECRET: str = "change-me-in-production-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # AI Logging Controls
    AI_LOG_INCLUDE_CONTENT: bool = False
    AI_LOG_MAX_CONTENT_CHARS: int = 500
    
    # AI Configuration
    SARVAM_API_KEY: Optional[str] = None
    SARVAM_MODEL: str = "sarvam-105b"
    SARVAM_MAX_TOKENS: int = 4096
    SARVAM_MAX_INPUT_CHARS: int = 16000

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Return normalized CORS origins from comma-separated env value."""
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()