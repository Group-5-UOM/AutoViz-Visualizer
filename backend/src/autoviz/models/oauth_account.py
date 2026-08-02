"""Linked OAuth identities (Google / GitHub / …) for a User."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="oauth_provider_identity_unique"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # e.g. "google", "github"
    provider = Column(String(50), nullable=False)
    # Google `sub` / GitHub numeric id — stable provider identity (not email).
    provider_user_id = Column(String(255), nullable=False)
    # Optional; used to revoke the grant on logout when present.
    access_token = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="oauth_accounts")
