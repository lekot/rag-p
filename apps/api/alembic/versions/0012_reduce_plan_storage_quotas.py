"""reduce plan document quotas for indexed storage reserve

Revision ID: 0012_reduce_plan_storage_quotas
Revises: 0011_subscriptions
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_reduce_plan_storage_quotas"
down_revision: str | None = "0011_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE plans
            SET included_storage_bytes = CASE id
                WHEN 'personal' THEN 10485760
                WHEN 'pro' THEN 209715200
                WHEN 'corporate' THEN 838860800
                WHEN 'enterprise' THEN 10737418240
                ELSE included_storage_bytes
            END
            WHERE id IN ('personal', 'pro', 'corporate', 'enterprise')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE plans
            SET included_storage_bytes = CASE id
                WHEN 'personal' THEN 104857600
                WHEN 'pro' THEN 2147483648
                WHEN 'corporate' THEN 8589934592
                WHEN 'enterprise' THEN 107374182400
                ELSE included_storage_bytes
            END
            WHERE id IN ('personal', 'pro', 'corporate', 'enterprise')
            """
        )
    )
