"""Ensure users.username exists (display name)

Revision ID: 006_user_username
Revises: 005_oauth_access_token
Create Date: 2026-08-01
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_user_username"
down_revision: Union[str, None] = "005_oauth_access_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # May already exist on DBs that ran an earlier ad-hoc username migration.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")
