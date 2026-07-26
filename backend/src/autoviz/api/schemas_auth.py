"""Pydantic request/response models for the ``/auth`` routes.

Kept in a separate file from ``schemas.py`` (which is scoped to
dataset/analysis/chart models) to avoid merge collisions with other
route developers.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Requests ─────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """FR-01: registration payload."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")


class LoginRequest(BaseModel):
    """FR-04: login payload."""

    email: EmailStr
    password: str


# ── Responses ────────────────────────────────────────────────────────────


class UserResponse(BaseModel):
    """Returned on register, login, and ``GET /auth/me``."""

    id: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Generic success message (e.g. logout confirmation)."""

    message: str


class ErrorResponse(BaseModel):
    """Structured error body."""

    error: str
    detail: str | None = None
