"""Per-user / per-key sliding-window rate limits (process-local).

Used by the MCP capability-URL middleware and by HTTP agent routes that call
the planner (FR-81). Approximate per-worker ceilings — Redis can replace this
later without changing call sites.
"""

from __future__ import annotations

import time

_hits: dict[str, list[float]] = {}


def is_rate_limited(key: str, *, limit: int, window_s: float) -> bool:
    """Return True when `key` has already used `limit` hits in the window."""
    now = time.monotonic()
    window = _hits.setdefault(key, [])
    window[:] = [t for t in window if now - t < window_s]
    if len(window) >= limit:
        return True
    window.append(now)
    return False


def reset_rate_limits() -> None:
    """Test helper: clear all buckets."""
    _hits.clear()
