"""YooKassa: widen reference_id and add idempotency index

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Widen reference_id from String(36) to String(64) to accommodate
    # YooKassa payment IDs (UUID-format strings like "22e12f66-000f-5000-...")
    op.alter_column(
        "billing_transactions",
        "reference_id",
        type_=sa.String(64),
        existing_type=sa.String(36),
        existing_nullable=True,
    )

    # Partial unique index — enforces idempotency for YooKassa webhook callbacks:
    # a given payment_id can only produce one billing_transactions row.
    op.create_index(
        "uq_billing_tx_yookassa",
        "billing_transactions",
        ["reference_id"],
        unique=True,
        postgresql_where=sa.text("reference_type = 'yookassa_payment'"),
    )


def downgrade() -> None:
    op.drop_index("uq_billing_tx_yookassa", table_name="billing_transactions")
    op.alter_column(
        "billing_transactions",
        "reference_id",
        type_=sa.String(36),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
