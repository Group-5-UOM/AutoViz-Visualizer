"""add is_public to dashboard

Revision ID: 0f2d96ffda4d
Revises: c144c6d09e3c
Create Date: 2026-08-15 00:12:58.642877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f2d96ffda4d'
down_revision: Union[str, None] = 'c144c6d09e3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dashboards', sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('dashboards', 'is_public')
