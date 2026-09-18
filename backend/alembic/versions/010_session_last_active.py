"""Add last_active_at to sessions for idle logout (FR-14).

Revision ID: 010_session_last_active
Revises: 009_mcp_keys
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_session_last_active"
down_revision: Union[str, None] = "009_mcp_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "last_active_at")
