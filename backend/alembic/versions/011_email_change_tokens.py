"""Add email_change_tokens for verified email updates.

Revision ID: 011_email_change_tokens
Revises: 010_session_last_active
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_email_change_tokens"
down_revision: Union[str, None] = "010_session_last_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_change_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("new_email", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_change_tokens_user_id"),
        "email_change_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_change_tokens_token"),
        "email_change_tokens",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_change_tokens_token"), table_name="email_change_tokens")
    op.drop_index(op.f("ix_email_change_tokens_user_id"), table_name="email_change_tokens")
    op.drop_table("email_change_tokens")
