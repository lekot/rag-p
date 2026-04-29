"""api keys: expiration and scope (lifecycle)

Revision ID: 0014_api_key_lifecycle
Revises: 0013_document_storage_metadata
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_api_key_lifecycle"
down_revision: str | None = "0015_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Add columns: expires_at NULLABLE first, scope with default 'read', revoked_at nullable.
    op.add_column(
        "api_keys",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "scope",
            sa.String(length=16),
            nullable=False,
            server_default="read",
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill existing keys: expires_at = now() + 90d, scope = 'admin' (legacy permission set)
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "UPDATE api_keys "
                "SET expires_at = now() + interval '90 days', "
                "    scope = 'admin' "
                "WHERE expires_at IS NULL"
            )
        )
    elif dialect == "sqlite":
        op.execute(
            sa.text(
                "UPDATE api_keys "
                "SET expires_at = datetime('now', '+90 days'), "
                "    scope = 'admin' "
                "WHERE expires_at IS NULL"
            )
        )
    else:
        # Fallback (mysql/oracle): try ANSI-ish DATE_ADD
        op.execute(
            sa.text(
                "UPDATE api_keys "
                "SET expires_at = CURRENT_TIMESTAMP + INTERVAL '90' DAY, "
                "    scope = 'admin' "
                "WHERE expires_at IS NULL"
            )
        )

    # Now enforce NOT NULL on expires_at
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column(
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    op.create_index("ix_api_keys_expires_at", "api_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_expires_at", table_name="api_keys")
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("scope")
        batch_op.drop_column("expires_at")
