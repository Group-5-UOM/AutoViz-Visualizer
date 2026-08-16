"""Who is calling this MCP tool, and which datasets may they see?

Over stdio the question does not arise: one process serves one person, so the
process-wide ``REGISTRY`` *is* their registry. That assumption is baked into
every tool in ``server.py``, and it is correct — right up until the same server
is reachable over HTTP, at which point "the process" is everybody at once and a
shared registry means **any caller could read any dataset another caller had
touched**.

This module is the seam that makes both true at the same time:

* **No caller bound** (stdio, tests, the existing FastAPI wiring) →
  ``current_registry()`` returns the global ``REGISTRY``. Behaviour is byte-for-byte
  what it was.
* **A caller bound** (an authenticated HTTP MCP request) → it returns a
  ``ScopedRegistry`` that consults the ownership table on every lookup.

The scoping rule is deliberately strict: **a scoped caller can only see datasets
with an explicit ownership row naming them.** A dataset with no row is not
"unowned and therefore public", it is invisible — that is the safe direction to
fail, and it keeps datasets created by a local stdio session from leaking into a
remote one running in the same process.

Nothing here caches ownership. A registry lookup is already the cheap half of a
query (§3.3 of `Docs/24` puts a whole governed query at ~20 ms), and a stale
ownership decision is the one kind of staleness this layer must not have.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator

import pandas as pd

from autoviz.services.registry import REGISTRY, DatasetRecord, DatasetRegistry


@dataclass(frozen=True)
class McpCaller:
    """The authenticated identity behind one MCP request.

    ``profile`` rides along because the tool surface a key may use is a property
    of the key, not of the server — see `Docs/26 §4.4`.
    """

    user_id: str
    profile: str = "default"
    key_id: str | None = None


_caller: ContextVar[McpCaller | None] = ContextVar("autoviz_mcp_caller", default=None)


def current_caller() -> McpCaller | None:
    """The caller bound to this request, or None when running unscoped (stdio)."""
    return _caller.get()


def set_caller(caller: McpCaller | None) -> Token:
    return _caller.set(caller)


def reset_caller(token: Token) -> None:
    _caller.reset(token)


@contextmanager
def caller_scope(caller: McpCaller | None) -> Iterator[None]:
    """Bind `caller` for the duration of the block.

    A ContextVar rather than a thread-local: the MCP HTTP app is async, several
    requests share a thread, and a thread-local would hand one user's identity to
    another's coroutine.
    """
    token = set_caller(caller)
    try:
        yield
    finally:
        reset_caller(token)


class ScopedRegistry:
    """A per-user view of the shared registry.

    Deliberately *not* a subclass of ``DatasetRegistry``: it owns no cache of its
    own and must not inherit one. It wraps the shared instance so the LRU, the
    memory budget and the blob loader stay process-wide — two users querying the
    same 100 MiB frame should not hold two copies — while every lookup is gated
    on an ownership row.

    Duck-typed against the surface the services actually use (``new_id``,
    ``add``, ``get``, ``remove``, ``all``), which is why it can be passed
    anywhere a ``DatasetRegistry`` is expected.
    """

    def __init__(self, user_id: str, shared: DatasetRegistry = REGISTRY) -> None:
        self._user_id = user_id
        self._shared = shared

    # --- ownership ---------------------------------------------------------

    def _owns(self, dataset_id: str) -> bool:
        """Does this caller own `dataset_id`? Unknown datasets are not owned.

        Imported here rather than at module import: `storage` depends on
        `services`, and pulling it in at the top would make the MCP server
        require a database even when running over stdio with no database at all.
        """
        from autoviz.core.database import get_sessionmaker
        from autoviz.storage import repository

        session = get_sessionmaker()()
        try:
            meta = repository.get_dataset_meta(session, dataset_id)
            return meta is not None and meta.user_id == self._user_id
        finally:
            session.close()

    def _owned_ids(self) -> set[str]:
        from autoviz.core.database import get_sessionmaker
        from autoviz.storage import repository

        session = get_sessionmaker()()
        try:
            return {m.dataset_id for m in repository.list_dataset_meta(session, self._user_id)}
        finally:
            session.close()

    # --- DatasetRegistry surface -------------------------------------------

    def new_id(self, source: str) -> str:
        return self._shared.new_id(source)

    def add(self, record: DatasetRecord) -> None:
        """Cache the frame *and* record who it belongs to.

        Both halves are required. Without the ownership row the dataset would be
        invisible to the very caller that just created it, because `get` denies
        anything it cannot attribute.
        """
        self._shared.add(record)
        self._claim(record)

    def _claim(self, record: DatasetRecord) -> None:
        from autoviz.core.database import get_sessionmaker
        from autoviz.models import UserDataset
        from autoviz.storage import repository

        session = get_sessionmaker()()
        try:
            if repository.get_dataset_meta(session, record.dataset_id) is not None:
                return  # already attributed; never silently re-assign an owner
            frame: pd.DataFrame = record.df
            session.add(
                UserDataset(
                    user_id=self._user_id,
                    dataset_id=record.dataset_id,
                    filename=record.source,
                    # Registered through MCP rather than uploaded, so there is no
                    # file under uploads/. The source string is the only locator
                    # there is, and recording it beats inventing a path.
                    file_path=record.source,
                    row_count=int(len(frame)),
                    column_count=int(len(frame.columns)),
                )
            )
            session.commit()
        finally:
            session.close()

    def get(self, dataset_id: str) -> DatasetRecord | None:
        """The record, or None when this caller does not own it.

        Returning None rather than raising is what makes the existing
        ``UNKNOWN_DATASET`` error the response to someone else's id — a caller
        learns nothing about whether the dataset exists, only that it is not
        theirs to read.
        """
        if not self._owns(dataset_id):
            return None
        return self._shared.get(dataset_id)

    def remove(self, dataset_id: str) -> bool:
        if not self._owns(dataset_id):
            return False
        from autoviz.core.database import get_sessionmaker
        from autoviz.storage import repository

        session = get_sessionmaker()()
        try:
            repository.delete_dataset_meta(session, dataset_id)
        finally:
            session.close()
        return self._shared.remove(dataset_id)

    def all(self) -> list[DatasetRecord]:
        """Only this caller's datasets, and only those still resident."""
        owned = self._owned_ids()
        return [r for r in self._shared.all() if r.dataset_id in owned]

    # `loader` is read by DatasetRegistry.get on a miss; delegate so a scoped
    # caller still benefits from blob restore.
    @property
    def loader(self) -> Any:
        return self._shared.loader


def current_registry() -> Any:
    """The registry this request may use.

    The single call every MCP tool should make instead of importing ``REGISTRY``.
    """
    caller = _caller.get()
    if caller is None:
        return REGISTRY
    return ScopedRegistry(caller.user_id)
