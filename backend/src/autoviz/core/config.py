"""Application settings — loaded from environment / .env file."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "AutoViz AI"
    API_V1_STR: str = "/api/v1"

    # ── Database (Neon DB) ──────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/autoviz",
    )

    # ── JWT ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Uploads ──────────────────────────────────────────────────────────
    # Default: backend/uploads/  (parents[3] from core/config.py → backend/)
    UPLOAD_DIR: Path = Path(__file__).resolve().parents[3] / "uploads"

    # ── CORS (Vite default 5173; Next/other 3000) ─────────────────────────
    AUTOVIZ_CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
