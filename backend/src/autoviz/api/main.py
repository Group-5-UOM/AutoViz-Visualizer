"""FastAPI application factory — the AutoViz HTTP API Gateway (Proposal §4.2).

Every route is a thin adapter over the same `services.*` / `agent.*` functions the
MCP server exposes, so behaviour can never diverge between the two entry paths.
Run: `uv --directory backend run uvicorn autoviz.api.main:app --reload`.
"""

import json
import logging
import os
from urllib.parse import urlparse
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from autoviz.api.routes import (
    agent,
    analysis,
    auth,
    charts,
    conversations,
    dashboards,
    datasets,
)
from autoviz.observability import configure_logging

_log = logging.getLogger("autoviz.observability")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Best-effort: create tables if the DB is reachable. A missing database must
    # not stop the non-DB routes (health, analysis, charts) from serving.
    from autoviz.core.database import init_db

    try:
        init_db()
    except Exception as exc:  # pragma: no cover - depends on a live DB
        _log.warning("DB init skipped (%s); persistence routes will error until a DB is up", exc)

    # Teach the shared registry how to restore a dataset it does not have cached
    # — after an eviction or a restart. Injected here rather than imported by
    # services/, which must not depend on the storage layer.
    from autoviz.services.registry import REGISTRY
    from autoviz.storage import blobs

    REGISTRY.loader = blobs.make_loader()

    # The Streamable HTTP transport keeps a task group for its sessions and
    # refuses to serve a request until it has been started ("Task group is not
    # initialized"). Mounting a sub-app does not run its lifespan, so the
    # manager has to be started here, in the parent's.
    manager = getattr(app.state, "mcp_session_manager", None)
    if manager is not None:
        async with manager.run():
            _log.info(json.dumps({"remote_mcp": "session manager running"}))
            yield
        return
    yield


def _cors_origins() -> list[str]:
    raw = os.environ.get("AUTOVIZ_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Vite's dev server (5173) first — the frontend's default. 3000 stays for
    # anyone running it behind a different dev server.
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def create_app() -> FastAPI:
    configure_logging()  # stderr + rotating file; safe to call repeatedly
    app = FastAPI(title="AutoViz AI", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        # One structured line per HTTP call — the transport-level companion to the
        # @observed decorator on MCP tools. No bodies/headers logged (no secrets).
        started = time.perf_counter()
        response = await call_next(request)
        _log.info(
            json.dumps(
                {
                    "http": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
    app.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
    app.include_router(charts.router, prefix="/charts", tags=["charts"])
    app.include_router(dashboards.router, prefix="/dashboards", tags=["dashboards"])
    app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
    app.include_router(agent.router, prefix="/agent", tags=["agent"])

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_remote_mcp(app)
    return app


def _remote_mcp_enabled() -> bool:
    """Remote MCP is opt-in: the endpoint is publicly reachable and authenticated
    only by a capability URL, so a deployment must ask for it explicitly rather
    than acquire it by upgrading."""
    return os.environ.get("AUTOVIZ_REMOTE_MCP", "").strip().lower() in ("1", "true", "yes")


def _mcp_allowed_hosts() -> list[str]:
    """Host header values the MCP transport will answer to.

    The transport ships DNS-rebinding protection on by default and rejects any
    Host it was not told about with a 421 — including the real public one, which
    is why this is derived rather than left empty. nginx forwards the original
    Host, so the value that arrives is the domain the user typed.
    """
    raw = os.environ.get("AUTOVIZ_MCP_ALLOWED_HOSTS", "").strip()
    if raw:
        return [h.strip() for h in raw.split(",") if h.strip()]
    hosts = ["localhost", "127.0.0.1", "testserver"]
    public = os.environ.get("AUTOVIZ_API_PUBLIC_URL", "").strip()
    if public:
        parsed = urlparse(public)
        if parsed.hostname:
            hosts.append(parsed.hostname)
            if parsed.port:
                hosts.append(f"{parsed.hostname}:{parsed.port}")
    return hosts


def _mcp_transport_security() -> "TransportSecuritySettings":
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = _mcp_allowed_hosts()
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        # Origin is not sent by a server-side MCP host, and an empty list would
        # reject browser-originated requests outright. Mirror the host list so a
        # future browser client is not silently blocked.
        allowed_origins=[f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts],
    )


def _mount_remote_mcp(app: FastAPI) -> None:
    """Serve the MCP server over Streamable HTTP at `/c/<key>/mcp`.

    Off unless AUTOVIZ_REMOTE_MCP=1. The endpoint is publicly reachable and
    authenticated only by a capability URL, so it is opt-in rather than
    something a deployment acquires by upgrading (`Docs/26`).

    Mounted behind `McpKeyAuthMiddleware`, which strips the key from the path and
    binds the caller — without it the tools would resolve the *global* registry
    and every link would read every user's data.
    """
    if not _remote_mcp_enabled():
        return
    try:
        from autoviz.api.mcp_auth import McpKeyAuthMiddleware
        from autoviz.core.database import get_sessionmaker
        from autoviz.mcp.server import mcp

        # Stateless: this sits behind nginx and may be replicated, so a client
        # must not have to return to the same worker to finish a session.
        mcp.settings.stateless_http = True
        mcp.settings.transport_security = _mcp_transport_security()
        # A fresh session manager for this app. `streamable_http_app()` caches
        # one on the FastMCP singleton and `run()` may be entered only once per
        # instance, so a second create_app() in the same process — tests, or a
        # server that builds the app twice — would otherwise fail at startup with
        # "can only be called once". There is no public reset; this is the seam.
        mcp._session_manager = None
        http_app = mcp.streamable_http_app()
        app.state.mcp_session_manager = mcp.session_manager
        app.mount(
            "/c",
            McpKeyAuthMiddleware(
                http_app, lambda: get_sessionmaker()(), mount_path="/c"
            ),
        )
        _log.info(json.dumps({"remote_mcp": "mounted", "path": "/c/{key}/mcp"}))
    except Exception as exc:  # pragma: no cover - never block API startup
        _log.error(json.dumps({"remote_mcp": "mount_failed", "error": str(exc)}))


app = create_app()
