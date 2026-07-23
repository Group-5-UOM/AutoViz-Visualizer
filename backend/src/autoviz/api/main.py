"""FastAPI application factory.

Run target::

    uvicorn autoviz.api.main:app --reload

CORS middleware is configured for the Next.js frontend (localhost:3000).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autoviz.api.routes import auth, datasets


def create_app() -> FastAPI:
    app = FastAPI(title="AutoViz AI")

    # CORS — allow the Next.js frontend during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────────────────────
    app.include_router(auth.router, prefix="/auth")
    app.include_router(datasets.router, prefix="/datasets")
    # analysis.router and charts.router will be added in later weeks

    @app.get("/health")
    def health_check():
        return {"status": "ok", "app": "AutoViz AI"}

    return app


app = create_app()
