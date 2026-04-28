"""org_balances and billing_transactions tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_balances",
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            primary_key=True,
        ),
        sa.Column(
            "balance_usd",
            sa.Numeric(14, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "billing_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("amount_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("balance_after_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_billing_tx_org_created",
        "billing_transactions",
        ["org_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_billing_tx_org_created", table_name="billing_transactions")
    op.drop_table("billing_transactions")
    op.drop_table("org_balances")
