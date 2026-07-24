"""SQLAlchemy engine, session factory, and declarative base.

PostgreSQL (Neon) is the deployment target; the URL comes from
``settings.DATABASE_URL``. The engine is built lazily so an offline test can point
``DATABASE_URL`` at a throwaway SQLite file (portable column types make the schema
identical) and rebuild via :func:`reset_engine` before the first session.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from autoviz.core.config import settings

Base = declarative_base()

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _db_url() -> str:
    # An explicit env var wins (tests point it at sqlite); else the configured URL.
    return os.getenv("DATABASE_URL", settings.DATABASE_URL)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _db_url()
        # SQLite (tests) needs check_same_thread off for the TestClient's threads.
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (offline/dev). Importing models registers them on Base.

    Production schema is managed by Alembic; this create_all is what the SQLite
    test DB and a quick local run use.
    """
    import autoviz.models  # noqa: F401 — registers every model on Base.metadata

    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Test hook: dispose and drop the cached engine/sessionmaker so a changed
    ``DATABASE_URL`` takes effect on the next access."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
