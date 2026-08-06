"""FastAPI application factory — the AutoViz HTTP API Gateway (Proposal §4.2).

Every route is a thin adapter over the same `services.*` / `agent.*` functions the
MCP server exposes, so behaviour can never diverge between the two entry paths.
Run: `uv --directory backend run uvicorn autoviz.api.main:app --reload`.
"""

import json
import logging
import os
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

    return app


app = create_app()
