"""FastAPI adapter layer (Week 3) — HTTP routes over the same autoviz.services.

Layout (all currently docstring stubs; see each module for its planned surface):

    main.py      FastAPI app factory (`create_app()`), CORS for the Next.js frontend
    deps.py      shared DI: the process-wide REGISTRY + lazy AgentService singleton
    schemas.py   request models (reuses schema.analysis_plan — grammar never redefined)
    routes/
        datasets.py   MCP tools 1-6   + a multipart /upload route
        analysis.py   MCP tools 7, 8, 11
        charts.py     MCP tools 9, 10, 12
        agent.py      MCP tools 13, 14 (LangGraph analyze / answer_clarification)

Design rule (Docs/06 §1): routes are thin typed adapters mirroring the MCP tools —
all business logic stays in autoviz.services / autoviz.agent, so both surfaces
return identical shapes and share one in-memory dataset registry per process.
"""
