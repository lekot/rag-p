"""pipeline_dataset_link

Revision ID: 0004
Revises: 0003
Create Date: 2025-04-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipelines",
        sa.Column("dataset_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_pipelines_dataset_id",
        "pipelines",
        "datasets",
        ["dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pipelines_dataset_id", "pipelines", type_="foreignkey")
    op.drop_column("pipelines", "dataset_id")
