"""Conversation routes — the chat transcript behind a dashboard.

    GET    /conversations/{dashboard_id}   the caller's transcript for that dashboard
    PUT    /conversations/{dashboard_id}   replace it (messages + agent thread_id)
    DELETE /conversations/{dashboard_id}   drop it

Charts and layout have been persisted since 002; the chat that produced them was
browser-local until now, so reopening a board on another machine restored the
canvas with no history behind it. This is the missing half.

Every lookup is scoped to the caller's user_id, so one user can never read or
overwrite another's transcript even by naming their dashboard id.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db
from autoviz.models import Conversation, User
from autoviz.storage import repository

router = APIRouter()

# A transcript is small (tens of turns) but a client bug should not be able to
# push an unbounded write through, and content is free text from the agent.
MAX_MESSAGES = 500
MAX_CONTENT_CHARS = 20_000


class ChatOptionPayload(BaseModel):
    label: str
    detail: str | None = None
    technique: str | None = None
    recommended: bool | None = None


class ChatMessagePayload(BaseModel):
    # The frontend's own message id, stored so restored rows keep their React
    # keys. Not the primary key — the server mints its own.
    client_id: str | None = None
    role: str
    content: str = ""
    chart_id: str | None = None
    referenced_title: str | None = None
    options: list[ChatOptionPayload] | None = None
    timestamp_ms: int | None = None


class UpdateConversationRequest(BaseModel):
    messages: list[ChatMessagePayload] = Field(default_factory=list)
    thread_id: str | None = None


def _conversation_dict(conversation: Conversation | None, dashboard_id: str) -> dict[str, Any]:
    if conversation is None:
        # A board nobody has chatted on yet is an empty transcript, not a 404 —
        # the client would have to special-case the error to render the same
        # empty panel it renders for a conversation with no messages.
        return {"dashboard_id": dashboard_id, "thread_id": None, "messages": [], "updated_at": None}
    return {
        "dashboard_id": conversation.dashboard_id,
        "thread_id": conversation.thread_id,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "messages": [
            {
                "client_id": m.client_id,
                "role": m.role,
                "content": m.content,
                "chart_id": m.chart_id,
                "referenced_title": m.referenced_title,
                "options": m.options,
                "timestamp_ms": m.timestamp_ms,
            }
            for m in conversation.messages
        ],
    }


def _assert_dashboard_visible(db: Session, dashboard_id: str, user: User) -> None:
    """Reject writing a transcript against someone else's dashboard."""
    dashboard = repository.get_dashboard(db, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if dashboard.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this dashboard")


@router.get("/{dashboard_id}")
def get_one(
    dashboard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_dashboard_visible(db, dashboard_id, user)
    return _conversation_dict(repository.get_conversation(db, user.id, dashboard_id), dashboard_id)


@router.put("/{dashboard_id}")
def update(
    dashboard_id: str,
    body: UpdateConversationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_dashboard_visible(db, dashboard_id, user)

    if len(body.messages) > MAX_MESSAGES:
        raise HTTPException(
            status_code=400, detail=f"A conversation may hold at most {MAX_MESSAGES} messages"
        )
    for m in body.messages:
        if m.role not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail=f"Unknown message role: {m.role}")
        if len(m.content) > MAX_CONTENT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"A message may hold at most {MAX_CONTENT_CHARS} characters",
            )

    conversation = repository.set_conversation(
        db,
        user.id,
        dashboard_id,
        messages=[
            {
                "client_id": m.client_id,
                "role": m.role,
                "content": m.content,
                "chart_id": m.chart_id,
                "referenced_title": m.referenced_title,
                "options": [o.model_dump(exclude_none=True) for o in m.options]
                if m.options
                else None,
                "timestamp_ms": m.timestamp_ms,
            }
            for m in body.messages
        ],
        thread_id=body.thread_id,
    )
    return _conversation_dict(conversation, dashboard_id)


@router.delete("/{dashboard_id}")
def delete(
    dashboard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = repository.get_conversation(db, user.id, dashboard_id)
    if conversation is not None:
        repository.delete_conversation(db, conversation)
    return {"removed": True, "dashboard_id": dashboard_id}
