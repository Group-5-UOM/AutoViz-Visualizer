"""A user's connection key for the remote MCP endpoint.

One row per link a user has generated for an MCP host (`Docs/26 §4.1`). Kept
separate from ``UserSession`` on purpose: a credential pasted into a third-party
tool must be revocable **without logging the person out of their browser**, and
must carry a narrower scope than a full login session.

The plaintext key is never stored. ``token_hash`` holds its SHA-256, so a
database dump yields no working links — the same reasoning that makes
``PasswordResetToken`` store a hash rather than a token.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class McpKey(Base):
    __tablename__ = "mcp_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the key. The key itself is shown once, at creation, and is not
    # recoverable from this row.
    token_hash = Column(String, unique=True, index=True, nullable=False)
    # What the user called it — "Claude on my laptop". Purely for the revoke UI,
    # which is useless if every row looks the same.
    label = Column(String, nullable=False, default="")
    # Which tool surface this key exposes: host | default | advanced.
    profile = Column(String, nullable=False, default="host")

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # The only way a user can tell whether a link they have forgotten about is
    # still in use. Written at most once a minute — see api/mcp_auth.py.
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="mcp_keys")

    def is_usable(self, now: datetime | None = None) -> bool:
        """Revocation and expiry in one place, so no caller can check only half."""
        now = now or datetime.now(timezone.utc)
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        expires = self.expires_at
        # SQLite hands back naive datetimes; compare like with like rather than
        # raising TypeError on the offline test target.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > now
