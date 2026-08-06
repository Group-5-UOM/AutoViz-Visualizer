"""Conversation + chat message models — the transcript behind a dataset's board.

One conversation per (user, dataset), mirroring the dataset-centric board the UI
presents. It exists so ``thread_id`` has somewhere to live: the agent keys
refinements and paused runs off that id, and without it a reopened board can show
its history but not continue it.

``dataset_id`` is the registry id (the string the frontend calls ``datasetId``),
not ``datasets.id`` — same convention as ``SavedChart.dataset_id``, so no FK.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from autoviz.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "dataset_id", name="uq_conversation_user_dataset"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id = Column(String, index=True, nullable=False)
    # The agent thread this board was last talking on. Null until the first run
    # returns one, and deliberately nullable forever: a thread the backend has
    # forgotten is not an error, it just means the next message starts fresh.
    thread_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Position in the transcript. The order the user saw is the only order that
    # makes sense to restore, and timestamps alone cannot guarantee it — a reply
    # and the message that triggered it can land in the same millisecond.
    seq = Column(Integer, nullable=False)
    # The id the frontend minted for this message. Carried back on restore so
    # React keys stay stable across a reload rather than every row remounting.
    client_id = Column(String, nullable=True)
    role = Column(String, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    # The chart this message points at ("View on canvas"), and the chart the user
    # had attached when they sent it. Both are display-only on restore.
    chart_id = Column(String, nullable=True)
    referenced_title = Column(String, nullable=True)
    # Grounded answer buttons offered with a question. Shape varies by pause kind
    # — a cleaning choice carries row counts and a recommendation, a clarification
    # is plain labels — so this stays JSON rather than becoming its own table.
    options = Column(JSON, nullable=True)
    # The frontend's own Date.now() for the message, kept verbatim so a restored
    # transcript shows the times it was written, not the times it was saved.
    timestamp_ms = Column(BigInteger, nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
