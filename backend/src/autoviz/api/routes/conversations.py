"""Conversation routes — the chat transcript behind a dataset's board.

    GET    /conversations/{dataset_id}   the caller's transcript for that dataset
    PUT    /conversations/{dataset_id}   replace it (messages + agent thread_id)
    DELETE /conversations/{dataset_id}   drop it

Charts and layout have been persisted since 002; the chat that produced them was
browser-local until now, so reopening a board on another machine restored the
canvas with no history behind it. This is the missing half.

Every lookup is scoped to the caller's user_id, so one user can never read or
overwrite another's transcript even by naming their dataset id.
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


def _conversation_dict(conversation: Conversation | None, dataset_id: str) -> dict[str, Any]:
    if conversation is None:
        # A board nobody has chatted on yet is an empty transcript, not a 404 —
        # the client would have to special-case the error to render the same
        # empty panel it renders for a conversation with no messages.
        return {"dataset_id": dataset_id, "thread_id": None, "messages": [], "updated_at": None}
    return {
        "dataset_id": conversation.dataset_id,
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


def _assert_dataset_visible(db: Session, dataset_id: str, user: User) -> None:
    """Reject writing a transcript against someone else's dataset.

    A dataset with no metadata row is allowed through: conversations are keyed by
    user_id regardless, so the worst case is an orphan transcript for a dataset
    that was deleted — never another user's data.
    """
    meta = repository.get_dataset_meta(db, dataset_id)
    if meta is not None and meta.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this dataset")


@router.get("/{dataset_id}")
def get_one(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_dataset_visible(db, dataset_id, user)
    return _conversation_dict(repository.get_conversation(db, user.id, dataset_id), dataset_id)


@router.put("/{dataset_id}")
def update(
    dataset_id: str,
    body: UpdateConversationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_dataset_visible(db, dataset_id, user)

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
        dataset_id,
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
    return _conversation_dict(conversation, dataset_id)


@router.delete("/{dataset_id}")
def delete(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conversation = repository.get_conversation(db, user.id, dataset_id)
    if conversation is not None:
        repository.delete_conversation(db, conversation)
    return {"removed": True, "dataset_id": dataset_id}
