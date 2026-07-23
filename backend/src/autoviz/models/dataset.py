"""Persisted dataset metadata — links an uploaded CSV to a user and to the
in-memory ``register_dataset`` entry returned by ``services.dataset``."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class UserDataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The ID returned by services.dataset.register_dataset()
    dataset_id = Column(String, unique=True, index=True, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)  # path inside uploads/
    status = Column(String, default="ready", nullable=False)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="datasets")
