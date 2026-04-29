"""account deletion request fields

Revision ID: 0016_account_deletion
Revises: 0013_document_storage_metadata
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_account_deletion"
down_revision: str | None = "0014_experiment_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_users_deletion_requested_at",
        "users",
        ["deletion_requested_at"],
    )
    op.create_index(
        "idx_organizations_deletion_requested_at",
        "organizations",
        ["deletion_requested_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_organizations_deletion_requested_at", table_name="organizations")
    op.drop_index("idx_users_deletion_requested_at", table_name="users")
    op.drop_column("organizations", "deletion_requested_at")
    op.drop_column("users", "deletion_requested_at")
