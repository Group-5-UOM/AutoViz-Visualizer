"""oauth_accounts + email_verified + password_reset_tokens; drop inline oauth cols

Revision ID: 007_oauth_accounts
Revises: 006_user_username
Create Date: 2026-08-01
"""

from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "007_oauth_accounts"
down_revision: Union[str, None] = "006_user_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    user_cols = {c["name"] for c in insp.get_columns("users")}

    if "email_verified" not in user_cols:
        op.add_column(
            "users",
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if "oauth_accounts" not in tables:
        op.create_table(
            "oauth_accounts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("provider_user_id", sa.String(length=255), nullable=False),
            sa.Column("access_token", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider", "provider_user_id", name="oauth_provider_identity_unique"
            ),
        )
    oauth_indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes("oauth_accounts")}
    if "ix_oauth_accounts_user_id" not in oauth_indexes:
        op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    reset_indexes = {
        ix["name"] for ix in sa.inspect(conn).get_indexes("password_reset_tokens")
    }
    if "ix_password_reset_tokens_user_id" not in reset_indexes:
        op.create_index(
            "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
        )
    if "ix_password_reset_tokens_token" not in reset_indexes:
        op.create_index(
            "ix_password_reset_tokens_token",
            "password_reset_tokens",
            ["token"],
            unique=True,
        )

    # Re-read columns in case email_verified was just added.
    user_cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    if "oauth_provider" in user_cols and "oauth_subject" in user_cols:
        rows = conn.execute(
            sa.text(
                """
                SELECT id, oauth_provider, oauth_subject, oauth_access_token
                FROM users
                WHERE oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL
                """
            )
        ).fetchall()
        for row in rows:
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1 FROM oauth_accounts
                    WHERE provider = :provider AND provider_user_id = :provider_user_id
                    """
                ),
                {"provider": row[1], "provider_user_id": row[2]},
            ).fetchone()
            if exists:
                continue
            conn.execute(
                sa.text(
                    """
                    INSERT INTO oauth_accounts
                        (id, user_id, provider, provider_user_id, access_token, created_at)
                    VALUES
                        (:id, :user_id, :provider, :provider_user_id, :access_token, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "user_id": row[0],
                    "provider": row[1],
                    "provider_user_id": row[2],
                    "access_token": row[3],
                },
            )
        conn.execute(
            sa.text(
                """
                UPDATE users SET email_verified = TRUE
                WHERE oauth_provider IS NOT NULL
                """
            )
        )
        op.drop_index("ix_users_oauth_provider", table_name="users", if_exists=True)
        op.drop_index("ix_users_oauth_subject", table_name="users", if_exists=True)
        op.drop_column("users", "oauth_access_token")
        op.drop_column("users", "oauth_subject")
        op.drop_column("users", "oauth_provider")


def downgrade() -> None:
    op.add_column("users", sa.Column("oauth_provider", sa.String(), nullable=True))
    op.add_column("users", sa.Column("oauth_subject", sa.String(), nullable=True))
    op.add_column("users", sa.Column("oauth_access_token", sa.String(), nullable=True))
    op.create_index("ix_users_oauth_provider", "users", ["oauth_provider"])
    op.create_index("ix_users_oauth_subject", "users", ["oauth_subject"])

    op.drop_table("password_reset_tokens")
    op.drop_table("oauth_accounts")
    op.drop_column("users", "email_verified")
