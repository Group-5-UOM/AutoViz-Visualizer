"""Per-user connection keys for the remote MCP endpoint

One row per link a user generates for an MCP host. Separate from `sessions`
because a credential pasted into a third-party tool must be revocable without
logging the person out, and carries a narrower scope than a login token.

Only the SHA-256 of the key is stored, so this table yields no working links if
it is ever dumped.

Revision ID: 009_mcp_keys
Revises: 0f2d96ffda4d
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_mcp_keys"
down_revision: Union[str, None] = "0f2d96ffda4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_keys",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False, server_default=""),
        sa.Column("profile", sa.String(), nullable=False, server_default="host"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique: the hash is the lookup key on every single MCP request, so it has
    # to be indexed, and two keys hashing alike would be a collision worth
    # failing loudly on.
    op.create_index("ix_mcp_keys_token_hash", "mcp_keys", ["token_hash"], unique=True)
    op.create_index("ix_mcp_keys_user_id", "mcp_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_keys_user_id", table_name="mcp_keys")
    op.drop_index("ix_mcp_keys_token_hash", table_name="mcp_keys")
    op.drop_table("mcp_keys")
