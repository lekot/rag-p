"""usage_events and usage_daily tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("api_key_id", sa.String(36), nullable=True),
        sa.Column("pipeline_id", sa.String(36), nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
    )
    op.create_index(
        "idx_usage_events_org_ts",
        "usage_events",
        ["org_id", sa.text("ts DESC")],
    )
    op.create_index(
        "idx_usage_events_key",
        "usage_events",
        ["api_key_id", sa.text("ts DESC")],
    )

    op.create_table(
        "usage_daily",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("total_prompt_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_completion_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("org_id", "day", "model", name="uq_usage_daily_org_day_model"),
    )
    op.create_index(
        "idx_usage_daily_org_day",
        "usage_daily",
        ["org_id", sa.text("day DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_usage_daily_org_day", table_name="usage_daily")
    op.drop_table("usage_daily")

    op.drop_index("idx_usage_events_key", table_name="usage_events")
    op.drop_index("idx_usage_events_org_ts", table_name="usage_events")
    op.drop_table("usage_events")
