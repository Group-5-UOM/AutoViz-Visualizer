"""Shared FastAPI dependencies.

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
