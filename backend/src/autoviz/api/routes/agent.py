"""Agentic routes — thin adapters over AgentService (MCP tools 13-14, the
LangGraph workflow, Docs/08).

    POST /agent/analyze   -> {status, answer, charts, thread_id}
                             or {status: "waiting_for_user", question, options,
                                 interrupt_id, pending_count, thread_id}
    POST /agent/answer    -> resume a run paused on a clarification; echo back
                             interrupt_id to answer a specific pending decision

Requires GOOGLE_API_KEY for the real planner; tests inject a FakePlanner-backed
AgentService via the get_agent dependency override. The agent always returns a
structured envelope (its own `status`), so these routes respond 200 and let the
body carry the workflow outcome — mirroring the MCP tools.

Like every other route that touches user data, both endpoints are owner-scoped:
`dataset_id` goes through the same ownership + lazy-reload gate the dataset
routes use, so a dataset that fell out of the in-memory registry (e.g. after a
restart) is re-registered from its stored file instead of 404-ing mid-conversation.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from autoviz.api.deps import get_agent, get_current_user, get_db, get_registry
from autoviz.api.errors import respond
from autoviz.api.schemas import AnalyzeRequest, ClarificationRequest
from autoviz.models import User
from autoviz.services.registry import DatasetRegistry
from autoviz.storage import repository

router = APIRouter()


def _require_owned(db: Session, registry: DatasetRegistry, dataset_id: str, user: User) -> None:
    """Ownership + lazy reload into the registry; raises the matching HTTP error."""
    _, error = repository.resolve_dataset(db, registry, dataset_id, user.id)
    if error is not None:
        status = 403 if error.get("error_code") == repository.FORBIDDEN else 404
        raise HTTPException(status_code=status, detail=error["error"])


@router.post("/analyze")
def analyze(
    body: AnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
    agent=Depends(get_agent),
):
    if body.dataset_id is not None:
        _require_owned(db, registry, body.dataset_id, user)
    return respond(
        agent.run(
            body.request,
            dataset_id=body.dataset_id,
            file_ref=body.file_ref,
            thread_id=body.thread_id,
            chart_id=body.chart_id,
        )
    )


@router.post("/answer")
def answer(
    body: ClarificationRequest,
    user: User = Depends(get_current_user),
    agent=Depends(get_agent),
):
    return respond(agent.resume(body.thread_id, body.answer, body.interrupt_id))
