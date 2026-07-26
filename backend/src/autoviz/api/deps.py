"""Shared FastAPI dependencies.

Providers:
- ``get_db()``           — SQLAlchemy session (from core.database)
- ``get_current_user()`` — hybrid JWT + sessions auth via HttpOnly cookie
- ``get_registry()``     — the process-wide ``services.registry.REGISTRY``
  (planned, same instance the MCP server uses)
"""

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from autoviz.core.database import get_db
from autoviz.models.session import UserSession
from autoviz.models.user import User
from autoviz.services.auth import decode_access_token


def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Extract the authenticated user from the ``access_token`` HttpOnly cookie.

    Verification is hybrid (two stages):
    1. **JWT signature + expiry** — fast, no DB hit.
    2. **``sessions`` row existence + ``expires_at``** — one indexed lookup on
       ``sessions.token`` to confirm the session has not been revoked via logout.

    Any failure raises ``HTTPException(401)``.
    """
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Stage 1: JWT decode (signature + exp claim)
    user_id = decode_access_token(access_token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Stage 2: sessions row must exist and not be expired
    session = (
        db.query(UserSession)
        .filter(
            UserSession.token == access_token,
            UserSession.user_id == user_id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or not found",
        )
    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )

    # Load user
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

Providers are trivial so tests can override them via `app.dependency_overrides`
(inject a test registry, a `FakePlanner`-backed agent, or a throwaway DB session).
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from autoviz.core.database import get_db
from autoviz.models import User
from autoviz.services.registry import REGISTRY, DatasetRegistry
from autoviz.storage import repository

__all__ = ["get_registry", "get_agent", "get_db", "get_current_user"]


def get_registry() -> DatasetRegistry:
    """The process-wide dataset registry — the same instance the MCP server uses,
    so datasets registered over HTTP and over MCP are shared."""
    return REGISTRY


_agent = None


def get_agent():
    """Lazily-constructed singleton AgentService.

    Imported inside the function so the API can start without LangGraph or
    GOOGLE_API_KEY when only the non-agentic routes are used. Uses a durable
    PostgresSaver when AUTOVIZ_AGENT_CHECKPOINTER=postgres, else in-memory.
    """
    global _agent
    if _agent is None:
        from autoviz.agent.service import AgentService
        from autoviz.storage.checkpoint import make_agent_checkpointer

        _agent = AgentService(checkpointer=make_agent_checkpointer())
    return _agent


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the Bearer token to a User, or raise 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1]
    user = repository.get_user_for_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
