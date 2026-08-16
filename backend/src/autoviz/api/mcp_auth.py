"""Authenticating an MCP request that carries its credential in the URL.

The connection link is `https://host/c/<key>/mcp` (`Docs/26 §4.1`). The key is a
capability: possession of the URL *is* the authorisation, because the hosts this
has to work with offer no field for an API key or a custom header — Gemini
Enterprise's connector accepts "No Authentication" or OAuth 2.0 and nothing in
between.

This middleware turns that path segment into an authenticated `McpCaller` bound
for the life of the request, and rejects everything it cannot attribute. It is
the only thing standing between the internet and the scoped registry, so it is
written to fail closed at every branch.

Three properties are deliberate:

**The key never reaches a log.** Not this module's logs, not nginx's — the
deployment must also strip the path from its access log, or the credential is
written to disk on every request. That is the likeliest real-world leak and it
is not fixable from here; see `Docs/26 §5`.

**Lookup is a single indexed query on a hash**, so the work does not vary with
how many keys exist and cannot be timed to learn about them.

**`last_used_at` is throttled.** It is the only signal a user has that a
forgotten link is still live, and it is not worth an `UPDATE` per tool call.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from autoviz import observability
from autoviz.mcp.context import McpCaller, caller_scope

# Requests per key per window. Generous for a human driving a chat client, tight
# enough that a leaked link cannot be used to grind through the tool surface.
# This endpoint is unauthenticated in the conventional sense and publicly
# reachable, so *some* ceiling is not optional.
RATE_LIMIT_REQUESTS = 120
RATE_LIMIT_WINDOW_S = 60.0

# key_id -> [timestamps]. Process-local and therefore per-worker: an approximate
# ceiling, not a quota. A real limiter belongs in nginx or Redis; this exists so
# the endpoint is never completely ungoverned.
_hits: dict[str, list[float]] = {}


def _rate_limited(key_id: str) -> bool:
    now = time.monotonic()
    window = _hits.setdefault(key_id, [])
    window[:] = [t for t in window if now - t < RATE_LIMIT_WINDOW_S]
    if len(window) >= RATE_LIMIT_REQUESTS:
        return True
    window.append(now)
    return False


async def _send_error(send: Send, status: int, message: str) -> None:
    body = f'{{"error":"{message}"}}'.encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _split_key(path: str, mount_path: str = "") -> tuple[str | None, str]:
    """`/c/<key>/mcp` -> ("<key>", "/mcp"). Anything else -> (None, path).

    The key is stripped from the path before the request reaches the mounted MCP
    app, so the app sees the plain `/mcp` endpoint it expects and never has to
    know a credential was in the URL.

    `mount_path` is removed first when present. Starlette hands a mounted ASGI
    app the **full** path rather than the remainder — verified, not assumed —
    so without this the first segment read as the key is the mount prefix
    itself. Written to tolerate both behaviours, since which one applies is a
    Starlette version detail and not worth coupling to.
    """
    if mount_path and path.startswith(mount_path):
        path = path[len(mount_path):]
    parts = path.lstrip("/").split("/", 1)
    if not parts or not parts[0]:
        return None, path or "/"
    key = parts[0]
    rest = "/" + parts[1] if len(parts) > 1 else "/"
    return key, rest


class McpKeyAuthMiddleware:
    """ASGI middleware authenticating `/c/<key>/...` and binding the caller.

    Pure ASGI rather than a Starlette `BaseHTTPMiddleware`: the MCP transport is
    Streamable HTTP and streams its responses, and `BaseHTTPMiddleware` buffers
    the body, which would defeat the point of the transport.
    """

    def __init__(
        self,
        app: ASGIApp,
        session_factory: Callable[[], Any],
        mount_path: str = "",
    ) -> None:
        self.app = app
        self._session_factory = session_factory
        self._mount_path = mount_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key, rest = _split_key(scope.get("path", ""), self._mount_path)
        if not key:
            await _send_error(send, 404, "not found")
            return

        # Imported lazily so this module can be imported without a database
        # configured, matching how the rest of the API defers storage imports.
        from autoviz.storage import repository

        session = self._session_factory()
        try:
            row = repository.get_usable_mcp_key(session, key)
            if row is None:
                # One message for unknown, revoked and expired alike: a caller
                # holding a dead link learns that it is dead, not which kind of
                # dead, and a caller guessing learns nothing at all.
                observability.log_event("mcp_auth_rejected", reason="invalid_key")
                await _send_error(send, 401, "invalid or expired connection key")
                return
            if _rate_limited(row.id):
                observability.log_event("mcp_rate_limited", key_id=row.id)
                await _send_error(send, 429, "rate limit exceeded")
                return
            caller = McpCaller(user_id=row.user_id, profile=row.profile, key_id=row.id)
            repository.touch_mcp_key(session, row)
        finally:
            session.close()

        # Rewrite the path so the mounted app sees `/mcp`, not the credential.
        scope = dict(scope)
        scope["path"] = rest
        scope["raw_path"] = rest.encode()

        with caller_scope(caller):
            await self.app(scope, receive, send)
