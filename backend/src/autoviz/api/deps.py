"""Shared FastAPI dependencies (Week 3 — not yet implemented).

Planned providers:
- `get_registry()` — the process-wide `services.registry.REGISTRY` (same instance
  the MCP server uses, so datasets registered over HTTP and MCP are shared).
- `get_agent()` — a lazily-constructed singleton `agent.service.AgentService`,
  mirroring `_get_agent()` in `mcp/server.py` (import inside the function so the
  API can start without LangGraph/GOOGLE_API_KEY when only the granular routes
  are used).
"""
