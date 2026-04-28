"""document raw storage metadata

Revision ID: 0013_document_storage_metadata
Revises: 0012_reduce_plan_storage_quotas
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_document_storage_metadata"
down_revision: str | None = "0012_reduce_plan_storage_quotas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "raw_size_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column("documents", sa.Column("content_type", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "storage_backend",
            sa.String(length=32),
            nullable=False,
            server_default="transient",
        ),
    )
    op.add_column("documents", sa.Column("object_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "object_key")
    op.drop_column("documents", "storage_backend")
    op.drop_column("documents", "sha256")
    op.drop_column("documents", "content_type")
    op.drop_column("documents", "raw_size_bytes")
