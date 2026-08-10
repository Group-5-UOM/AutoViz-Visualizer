"""conversations + chat_messages — server-side chat history per (user, dataset)

Revision ID: 008_conversations
Revises: 007_oauth_accounts
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_conversations"
down_revision: Union[str, None] = "007_oauth_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())

    if "conversations" not in tables:
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("dataset_id", sa.String(), nullable=False),
            sa.Column("thread_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            # One transcript per board. The upsert in the repository relies on
            # this: without it a racing double-save would fork the history in two.
            sa.UniqueConstraint("user_id", "dataset_id", name="uq_conversation_user_dataset"),
        )
    conversation_indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes("conversations")}
    if "ix_conversations_user_id" not in conversation_indexes:
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    if "ix_conversations_dataset_id" not in conversation_indexes:
        op.create_index("ix_conversations_dataset_id", "conversations", ["dataset_id"])

    if "chat_messages" not in tables:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("chart_id", sa.String(), nullable=True),
            sa.Column("referenced_title", sa.String(), nullable=True),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("timestamp_ms", sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    message_indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes("chat_messages")}
    if "ix_chat_messages_conversation_id" not in message_indexes:
        op.create_index(
            "ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_dataset_id", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
