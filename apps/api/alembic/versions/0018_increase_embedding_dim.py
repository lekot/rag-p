"""increase embedding dimension to 3072

Bumps the chunks.embedding column from Vector(1024) to Vector(3072) so the
schema supports all common embedding models:
- bge-m3               → 1024 (current default on compose)
- text-embedding-3-small → 1536
- text-embedding-3-large → 3072
- cohere embed-multilingual-v3.0 → 1024

Existing pgvector ivfflat index (if any) must be recreated after ALTER TYPE.
The compose production has no index yet — sequential scan is used for the
current data volume, so no index rebuild is required.

Revision ID: 0018_increase_embedding_dim
Revises: 0017_password_reset_tokens
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018_increase_embedding_dim"
down_revision: Union[str, None] = "0017_password_reset_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector does not support ALTER COLUMN TYPE directly for vector columns
    # when data exists.  The safe approach:
    #   1. ALTER TABLE ... ALTER COLUMN ... TYPE vector(3072)
    #      (works if pgvector >= 0.5.0)
    #   2. Drop + recreate any ivfflat/hnsw index on embedding.
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(3072)")


def downgrade() -> None:
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")
