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

    # ── App URLs (OAuth redirects) — set in .env, never hardcode hosts here ──
    AUTOVIZ_FRONTEND_URL: str = ""
    AUTOVIZ_API_PUBLIC_URL: str = ""

    # ── OAuth ────────────────────────────────────────────────────────────
    GITHUB_OAUTH_CLIENT_ID: str = ""
    GITHUB_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    # Optional overrides. Empty → derived from AUTOVIZ_API_PUBLIC_URL.
    # Use only when the callback host differs from the API public URL.
    GITHUB_OAUTH_REDIRECT_URI: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""

    # When true, forgot-password responses include the reset token/URL (local only).
    AUTOVIZ_EXPOSE_RESET_TOKENS: bool = True

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def github_callback_url(self) -> str:
        override = self.GITHUB_OAUTH_REDIRECT_URI.strip()
        if override:
            return override
        return f"{self.AUTOVIZ_API_PUBLIC_URL.rstrip('/')}/auth/oauth/github/callback"

    @property
    def google_callback_url(self) -> str:
        override = self.GOOGLE_OAUTH_REDIRECT_URI.strip()
        if override:
            return override
        return f"{self.AUTOVIZ_API_PUBLIC_URL.rstrip('/')}/auth/oauth/google/callback"


settings = Settings()
