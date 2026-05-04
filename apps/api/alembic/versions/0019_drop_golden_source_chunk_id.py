"""drop source_chunk_id from dataset_golden_items

Golden Q&A is now generated from document text, not from individual chunks.
source_chunk_id FK made the evaluation brittle — re-chunking or document
deletion would NULL it out, breaking all retrieval_hit scores.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-04 18:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop FK first (may not exist on some envs), then the column
    conn = op.get_bind()
    # Check if the FK constraint exists
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'dataset_golden_items_source_chunk_id_fkey' "
            "AND table_name = 'dataset_golden_items'"
        )
    )
    if result.scalar():
        op.drop_constraint(
            "dataset_golden_items_source_chunk_id_fkey",
            "dataset_golden_items",
            type_="foreignkey",
        )
    # Drop column (safe to run even if already dropped)
    op.drop_column("dataset_golden_items", "source_chunk_id")


def downgrade() -> None:
    op.add_column(
        "dataset_golden_items",
        sa.Column(
            "source_chunk_id",
            sa.String(36),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
