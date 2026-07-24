"""Saved chart model — a persisted Vega-Lite spec owned by a user."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String

from autoviz.core.database import Base


class SavedChart(Base):
    __tablename__ = "saved_charts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name = Column(String, nullable=False)
    dataset_id = Column(String, nullable=True)  # the registry id this chart came from
    vega_lite_spec = Column(JSON, nullable=False)
    chart_spec = Column(JSON, nullable=True)
    provenance = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
