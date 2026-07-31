"""Saved charts, dashboards, dashboard widgets + dataset row/column counts

Revision ID: 002_charts_dashboards
Revises: 001_initial_schema
Create Date: 2026-07-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_charts_dashboards"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    # ── datasets: profiled row/column counts ─────────────────────────────
    # 001 was later edited to create these two columns in the initial table,
    # so a database built from the current 001 already has them while one
    # built from the original 001 does not. Add only what is missing —
    # unguarded add_column fails with DuplicateColumn on any fresh database.
    existing = _existing_columns("datasets")
    if "row_count" not in existing:
        op.add_column("datasets", sa.Column("row_count", sa.Integer(), nullable=True))
    if "column_count" not in existing:
        op.add_column("datasets", sa.Column("column_count", sa.Integer(), nullable=True))

    # ── saved_charts ─────────────────────────────────────────────────────
    op.create_table(
        "saved_charts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("vega_lite_spec", sa.JSON(), nullable=False),
        sa.Column("chart_spec", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_saved_charts_user_id"), "saved_charts", ["user_id"])

    # ── dashboards ───────────────────────────────────────────────────────
    op.create_table(
        "dashboards",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dashboards_user_id"), "dashboards", ["user_id"])

    # ── dashboard_widgets ────────────────────────────────────────────────
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dashboard_id", sa.String(), nullable=False),
        sa.Column("chart_id", sa.String(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=True),
        sa.Column("y", sa.Integer(), nullable=True),
        sa.Column("w", sa.Integer(), nullable=True),
        sa.Column("h", sa.Integer(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chart_id"], ["saved_charts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dashboard_widgets_dashboard_id"), "dashboard_widgets", ["dashboard_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dashboard_widgets_dashboard_id"), table_name="dashboard_widgets")
    op.drop_table("dashboard_widgets")
    op.drop_index(op.f("ix_dashboards_user_id"), table_name="dashboards")
    op.drop_table("dashboards")
    op.drop_index(op.f("ix_saved_charts_user_id"), table_name="saved_charts")
    op.drop_table("saved_charts")
    op.drop_column("datasets", "column_count")
    op.drop_column("datasets", "row_count")
