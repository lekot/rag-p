"""plans, org_subscriptions, subscription_events tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------
    # plans — catalogue of available subscription plans (static)
    # -----------------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("price_rub_monthly", sa.Numeric(12, 2), nullable=False),
        sa.Column("included_q", sa.BigInteger, nullable=False),
        sa.Column("included_storage_bytes", sa.BigInteger, nullable=False),
        sa.Column("max_users", sa.Integer, nullable=False),
        sa.Column("rpm_per_key", sa.Integer, nullable=False),
        sa.Column("allow_overage", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )

    # Seed the four canonical plans
    op.execute(
        sa.text(
            """
            INSERT INTO plans
              (id, name, price_rub_monthly, included_q, included_storage_bytes,
               max_users, rpm_per_key, allow_overage, is_active, sort_order)
            VALUES
              ('personal',   'Personal',   100,   1000,    104857600,    1,  60,   false, true, 1),
              ('pro',        'Pro',        1500,  20000,   2147483648,   5,  300,  false, true, 2),
              ('corporate',  'Corporate',  5000,  70000,   8589934592,   25, 1000, true,  true, 3),
              ('enterprise', 'Enterprise', 60000, 1000000, 107374182400, 0,  0,    true,  true, 4)
            """
        )
    )

    # -----------------------------------------------------------
    # org_subscriptions — current active subscription per org
    # -----------------------------------------------------------
    op.create_table(
        "org_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("plans.id"), nullable=False),
        # 'active' | 'expired' | 'cancelled'
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("q_used", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_bytes_used", sa.BigInteger, nullable=False, server_default="0"),
        # MVP: auto_renew always false — renewal is manual
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_org_sub_org_id", "org_subscriptions", ["org_id"])
    op.create_index(
        "idx_org_sub_period_end", "org_subscriptions", ["current_period_end"]
    )

    # -----------------------------------------------------------
    # subscription_events — audit history
    # -----------------------------------------------------------
    op.create_table(
        "subscription_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("plans.id"), nullable=False),
        # 'started' | 'renewed' | 'expired' | 'cancelled' | 'upgraded' | 'downgraded'
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yookassa_payment_id", sa.String(64), nullable=True),
        sa.Column("amount_rub", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_sub_events_org_id", "subscription_events", ["org_id"])
    op.create_unique_constraint(
        "uq_subscription_events_yookassa_payment_id",
        "subscription_events",
        ["yookassa_payment_id"],
    )

    # -----------------------------------------------------------
    # NOTE: org_balances is intentionally kept as the "overage wallet"
    # for Corporate/Enterprise plans.  No structural change needed.
    # -----------------------------------------------------------


def downgrade() -> None:
    op.drop_constraint(
        "uq_subscription_events_yookassa_payment_id",
        "subscription_events",
        type_="unique",
    )
    op.drop_index("idx_sub_events_org_id", table_name="subscription_events")
    op.drop_table("subscription_events")

    op.drop_index("idx_org_sub_period_end", table_name="org_subscriptions")
    op.drop_index("idx_org_sub_org_id", table_name="org_subscriptions")
    op.drop_table("org_subscriptions")

    op.drop_table("plans")
