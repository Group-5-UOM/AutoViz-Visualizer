"""Agentic routes — thin adapters over AgentService (MCP tools 13-14, the
LangGraph workflow, Docs/08).

    POST /agent/analyze   -> {status, answer, charts, thread_id}
                             or {status: "waiting_for_user", question, options, thread_id}
    POST /agent/answer    -> resume a run paused on a clarification

Requires GOOGLE_API_KEY for the real planner; tests inject a FakePlanner-backed
AgentService via the get_agent dependency override. The agent always returns a
structured envelope (its own `status`), so these routes respond 200 and let the
body carry the workflow outcome — mirroring the MCP tools.
"""

from fastapi import APIRouter, Depends

from autoviz.api.deps import get_agent
from autoviz.api.errors import respond
from autoviz.api.schemas import AnalyzeRequest, ClarificationRequest

router = APIRouter()


@router.post("/analyze")
def analyze(body: AnalyzeRequest, agent=Depends(get_agent)):
    return respond(
        agent.run(
            body.request,
            dataset_id=body.dataset_id,
            file_ref=body.file_ref,
            thread_id=body.thread_id,
        )
    )


@router.post("/answer")
def answer(body: ClarificationRequest, agent=Depends(get_agent)):
    return respond(agent.resume(body.thread_id, body.answer))
