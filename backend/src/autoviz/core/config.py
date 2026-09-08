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

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")

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

    # Idle session timeout in minutes (FR-14). Absolute token TTL still applies.
    AUTOVIZ_IDLE_TIMEOUT_MINUTES: int = 30

    # Dataset retention notice / remaining-days calculation (FR-35).
    AUTOVIZ_DATASET_RETENTION_DAYS: int = 90

    # Per-user LLM request budget (FR-81). Process-local sliding window.
    AUTOVIZ_LLM_RATE_LIMIT: int = 60
    AUTOVIZ_LLM_RATE_WINDOW_S: float = 3600.0

    # Planner identity recorded on chart provenance (FR-146).
    AUTOVIZ_PLANNER_PROVIDER: str = "google"

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
