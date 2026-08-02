"""User account model — local password optional; OAuth lives in oauth_accounts."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    # Display name shown in the UI (chosen at register or from OAuth profile).
    username = Column(String, unique=True, index=True, nullable=True)
    # Null until the user sets an AutoViz password (OAuth-only accounts).
    password_hash = Column(String, nullable=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    oauth_accounts = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )
    datasets = relationship(
        "UserDataset", back_populates="user", cascade="all, delete-orphan"
    )
