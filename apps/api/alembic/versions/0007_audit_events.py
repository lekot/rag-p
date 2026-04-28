"""audit_events table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_audit_events_org_created",
        "audit_events",
        ["org_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_events_user",
        "audit_events",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_events_resource",
        "audit_events",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_audit_events_resource", table_name="audit_events")
    op.drop_index("idx_audit_events_user", table_name="audit_events")
    op.drop_index("idx_audit_events_org_created", table_name="audit_events")
    op.drop_table("audit_events")
