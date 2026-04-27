"""Resize chunks.embedding from 1536 to 1024 to match Cohere v3 family

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("chunks", "embedding")
    op.add_column("chunks", sa.Column("embedding", Vector(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "embedding")
    op.add_column("chunks", sa.Column("embedding", Vector(1536), nullable=True))
