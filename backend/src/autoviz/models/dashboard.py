"""Dashboard + widget models — a persisted layout of saved-chart widgets."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class Dashboard(Base):
    __tablename__ = "dashboards"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    widgets = relationship(
        "DashboardWidget",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidget.order",
    )


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    dashboard_id = Column(
        String, ForeignKey("dashboards.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chart_id = Column(
        String, ForeignKey("saved_charts.id", ondelete="CASCADE"), nullable=False
    )
    x = Column(Integer, default=0)
    y = Column(Integer, default=0)
    w = Column(Integer, default=6)
    h = Column(Integer, default=4)
    order = Column(Integer, default=0)

    dashboard = relationship("Dashboard", back_populates="widgets")
