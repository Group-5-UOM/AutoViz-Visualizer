"""Data-access helpers over the ORM models (``autoviz.models``).

Thin CRUD returning ORM objects or plain values; the API routes shape them into
responses. ``resolve_dataset`` is the ownership + lazy-reload gate every dataset
route goes through.
"""

import datetime
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from autoviz.errors import UNKNOWN_DATASET, make_error
from autoviz.models import (
    Dashboard,
    DashboardWidget,
    SavedChart,
    User,
    UserDataset,
    UserSession,
)
from autoviz.services.registry import DatasetRegistry

FORBIDDEN = "FORBIDDEN"  # API-level code (not a service taxonomy code); maps to 403


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- users & tokens ----------------------------------------------------------


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def create_user(
    session: Session,
    email: str,
    password_hash: str,
    username: str | None = None,
) -> User:
    user = User(email=email, password_hash=password_hash, username=username)
    session.add(user)
    session.commit()
    return user


def create_token(session: Session, user_id: str, ttl_hours: int = 24 * 7) -> UserSession:
    token = UserSession(
        token=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=_now() + datetime.timedelta(hours=ttl_hours),
    )
    session.add(token)
    session.commit()
    return token


def get_user_for_token(session: Session, token: str) -> User | None:
    row = session.scalar(select(UserSession).where(UserSession.token == token))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite returns naive; treat stored time as UTC
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    if expires <= _now():
        return None
    return session.get(User, row.user_id)


def delete_token(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token == token))
    if row is not None:
        session.delete(row)
        session.commit()


# --- dataset metadata --------------------------------------------------------


def add_dataset_meta(
    session: Session,
    *,
    dataset_id: str,
    user_id: str,
    filename: str,
    file_path: str,
    row_count: int | None = None,
    column_count: int | None = None,
    size_bytes: int | None = None,
) -> UserDataset:
    existing = get_dataset_meta(session, dataset_id)
    if existing is not None:  # idempotent re-upload of the same registry id
        existing.filename = filename
        existing.file_path = file_path
        existing.row_count = row_count
        existing.column_count = column_count
        existing.size_bytes = size_bytes
        session.commit()
        return existing
    meta = UserDataset(
        user_id=user_id,
        dataset_id=dataset_id,
        filename=filename,
        file_path=file_path,
        row_count=row_count,
        column_count=column_count,
        size_bytes=size_bytes,
    )
    session.add(meta)
    session.commit()
    return meta


def get_dataset_meta(session: Session, dataset_id: str) -> UserDataset | None:
    return session.scalar(select(UserDataset).where(UserDataset.dataset_id == dataset_id))


def list_dataset_meta(session: Session, user_id: str) -> list[UserDataset]:
    return list(session.scalars(select(UserDataset).where(UserDataset.user_id == user_id)))


def delete_dataset_meta(session: Session, dataset_id: str) -> None:
    meta = get_dataset_meta(session, dataset_id)
    if meta is not None:
        session.delete(meta)
        session.commit()


def _reload_into_registry(registry: DatasetRegistry, meta: UserDataset):
    """Re-register the dataset from its stored file, keeping its durable id.

    Reuses the full ``register_dataset`` path (limits, profiling, neutralization),
    then re-keys the fresh record to the persisted dataset_id.
    """
    from autoviz.services.dataset import register_dataset

    res = register_dataset(meta.file_path, registry)
    if "error" in res:
        return None
    fresh_id = res["dataset_id"]
    record = registry.get(fresh_id)
    registry.remove(fresh_id)
    record.dataset_id = meta.dataset_id
    registry.add(record)
    return record


def resolve_dataset(session: Session, registry: DatasetRegistry, dataset_id: str, user_id: str):
    """Return (record, error). Enforces ownership and lazily reloads the DataFrame
    from disk if it fell out of the in-memory registry (e.g. after a restart)."""
    meta = get_dataset_meta(session, dataset_id)
    if meta is None:
        return None, make_error(UNKNOWN_DATASET, f"Unknown dataset_id: {dataset_id}")
    if meta.user_id != user_id:
        return None, {"error": "You do not own this dataset", "error_code": FORBIDDEN}
    record = registry.get(dataset_id)
    if record is None:
        record = _reload_into_registry(registry, meta)
        if record is None:
            return None, make_error(
                UNKNOWN_DATASET, f"Dataset file for {dataset_id} is no longer available"
            )
    return record, None


# --- saved charts ------------------------------------------------------------


def create_chart(session: Session, user_id: str, **fields) -> SavedChart:
    chart = SavedChart(user_id=user_id, **fields)
    session.add(chart)
    session.commit()
    return chart


def get_chart(session: Session, chart_id: str) -> SavedChart | None:
    return session.get(SavedChart, chart_id)


def list_charts(session: Session, user_id: str) -> list[SavedChart]:
    return list(session.scalars(select(SavedChart).where(SavedChart.user_id == user_id)))


def delete_chart(session: Session, chart: SavedChart) -> None:
    session.delete(chart)
    session.commit()


# --- dashboards --------------------------------------------------------------


def create_dashboard(session: Session, user_id: str, name: str) -> Dashboard:
    dashboard = Dashboard(user_id=user_id, name=name)
    session.add(dashboard)
    session.commit()
    return dashboard


def get_dashboard(session: Session, dashboard_id: str) -> Dashboard | None:
    return session.get(Dashboard, dashboard_id)


def list_dashboards(session: Session, user_id: str) -> list[Dashboard]:
    return list(session.scalars(select(Dashboard).where(Dashboard.user_id == user_id)))


def set_dashboard_widgets(session: Session, dashboard: Dashboard, widgets: list[dict]) -> Dashboard:
    """Replace a dashboard's widgets with the given [{chart_id, x, y, w, h, order}]."""
    dashboard.widgets.clear()
    for i, w in enumerate(widgets):
        dashboard.widgets.append(
            DashboardWidget(
                chart_id=w["chart_id"],
                x=int(w.get("x", 0)),
                y=int(w.get("y", 0)),
                w=int(w.get("w", 6)),
                h=int(w.get("h", 4)),
                order=int(w.get("order", i)),
            )
        )
    session.commit()
    return dashboard


def delete_dashboard(session: Session, dashboard: Dashboard) -> None:
    session.delete(dashboard)
    session.commit()
