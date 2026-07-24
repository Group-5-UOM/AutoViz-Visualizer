"""Optional durable LangGraph checkpointer backed by PostgreSQL.

Off by default (the agent uses the in-memory saver). Set
``AUTOVIZ_AGENT_CHECKPOINTER=postgres`` to persist conversation threads across
restarts. Defensive: any setup failure falls back to in-memory (returns None),
so a missing/unreachable database never breaks the agent.
"""

import logging
import os

from autoviz.core.config import settings

_log = logging.getLogger("autoviz.observability")


def make_agent_checkpointer():
    """Return a PostgresSaver when explicitly enabled and reachable, else None
    (the caller then defaults to InMemorySaver)."""
    if os.environ.get("AUTOVIZ_AGENT_CHECKPOINTER", "").lower() != "postgres":
        return None
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
        # PostgresSaver wants a libpq conn string, not a SQLAlchemy '+driver' form.
        conn_str = url.replace("postgresql+psycopg://", "postgresql://").replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        conn = Connection.connect(conn_str, autocommit=True)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    except Exception as exc:  # pragma: no cover - depends on a live Postgres
        _log.warning("PostgresSaver unavailable; using in-memory checkpoints: %s", exc)
        return None
