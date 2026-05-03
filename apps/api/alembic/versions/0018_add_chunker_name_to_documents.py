"""add chunker_name to documents

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-03 17:06:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("chunker_name", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "chunker_name")
