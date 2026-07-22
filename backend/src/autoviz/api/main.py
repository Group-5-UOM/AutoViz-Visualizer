"""FastAPI app factory (Week 3 — not yet implemented).

Planned:

    from fastapi import FastAPI

    def create_app() -> FastAPI:
        app = FastAPI(title="AutoViz AI")
        app.include_router(datasets.router, prefix="/datasets")
        app.include_router(analysis.router, prefix="/analysis")
        app.include_router(charts.router, prefix="/charts")
        app.include_router(agent.router, prefix="/agent")
        return app

Run target: `uv run uvicorn autoviz.api.main:app --reload` once implemented.
CORS middleware will be needed for the Next.js frontend (localhost:3000).

Requires adding `fastapi` + `uvicorn` to pyproject.toml — deliberately not added
yet so the MCP-only install stays lean.
"""
