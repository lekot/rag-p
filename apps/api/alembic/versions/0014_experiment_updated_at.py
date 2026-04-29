"""experiment updated_at column + watchdog index

Revision ID: 0014_experiment_updated_at
Revises: 0013_document_storage_metadata
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_experiment_updated_at"
down_revision: str | None = "0013_document_storage_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Backfill: existing rows get updated_at = created_at so they don't look
    # stale to the watchdog the moment the migration lands.
    op.execute(
        "UPDATE experiments SET updated_at = created_at WHERE updated_at IS NOT NULL"
    )
    op.create_index(
        "ix_experiments_status_updated_at",
        "experiments",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiments_status_updated_at", table_name="experiments")
    op.drop_column("experiments", "updated_at")
