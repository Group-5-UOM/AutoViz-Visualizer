"""Durable dataset payloads (Parquet bytes + cached schema/profile)

Makes a dataset survive a restart without the upload file: the rows move from
local disk into the database, and the registry becomes a bounded cache in front
of this table.

Revision ID: 003_dataset_blobs
Revises: 002_charts_dashboards
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_dataset_blobs"
down_revision: Union[str, None] = "002_charts_dashboards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_blobs",
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("parquet", sa.LargeBinary(), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("categorical_numeric", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.dataset_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("dataset_id"),
    )
    # Datasets registered before this migration have no blob. They keep working
    # through the loader's CSV fallback (storage/blobs.py), which backfills a
    # blob the first time such a dataset is touched — no data migration here,
    # since re-reading every upload at deploy time would be slow and can fail.


def downgrade() -> None:
    op.drop_table("dataset_blobs")
