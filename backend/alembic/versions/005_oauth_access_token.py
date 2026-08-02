"""Store OAuth access token for revoke-on-logout

Revision ID: 005_oauth_access_token
Revises: 004_oauth_users
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_oauth_access_token"
down_revision: Union[str, None] = "004_oauth_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oauth_access_token", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "oauth_access_token")
