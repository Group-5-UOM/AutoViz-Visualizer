"""Agentic routes (Week 3 — not yet implemented).

Thin adapters over `agent.service.AgentService`, identical behavior to MCP
tools 13-14 (the LangGraph workflow, Docs/08):

    POST /agent/analyze   AgentService.run(request, dataset_id?, file_ref?, thread_id?)
                          -> {status, answer, charts, thread_id}
                          or {status: "waiting_for_user", question, options, thread_id}
    POST /agent/answer    AgentService.resume(thread_id, answer)

Requires GOOGLE_API_KEY (backend/.env). The frontend chat panel drives these
two routes: reuse `thread_id` for refinements; render the `waiting_for_user`
shape as a clarification prompt.
"""
