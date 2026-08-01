"""Allow OAuth-only users (nullable password + provider subject)

Revision ID: 004_oauth_users
Revises: 003_dataset_blobs
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_oauth_users"
down_revision: Union[str, None] = "003_dataset_blobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)
    op.add_column("users", sa.Column("oauth_provider", sa.String(), nullable=True))
    op.add_column("users", sa.Column("oauth_subject", sa.String(), nullable=True))
    op.create_index(op.f("ix_users_oauth_provider"), "users", ["oauth_provider"])
    op.create_index(op.f("ix_users_oauth_subject"), "users", ["oauth_subject"])
    op.create_index(
        "ix_users_oauth_provider_subject",
        "users",
        ["oauth_provider", "oauth_subject"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_oauth_provider_subject", table_name="users")
    op.drop_index(op.f("ix_users_oauth_subject"), table_name="users")
    op.drop_index(op.f("ix_users_oauth_provider"), table_name="users")
    op.drop_column("users", "oauth_subject")
    op.drop_column("users", "oauth_provider")
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
