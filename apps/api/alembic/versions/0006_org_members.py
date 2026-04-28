"""org_members and org_invites tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create org_members table
    op.create_table(
        "org_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
    )
    op.create_index("ix_org_members_org_id", "org_members", ["org_id"])
    op.create_index("ix_org_members_user_id", "org_members", ["user_id"])

    # Migrate existing memberships into org_members.
    # id is String(36) (UUID), so generate fresh uuid for each row instead of
    # concatenating org_id + '-' + user_id (which gives 73 chars and overflows).
    op.execute(
        sa.text(
            "INSERT INTO org_members (id, org_id, user_id, role, created_at) "
            "SELECT "
            "  gen_random_uuid()::text as id, "
            "  organization_id as org_id, "
            "  user_id, "
            "  role, "
            "  NOW() "
            "FROM memberships "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Create org_invites table
    op.create_table(
        "org_invites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_org_invites_token_hash", "org_invites", ["token_hash"])
    op.create_index("ix_org_invites_org_id_email", "org_invites", ["org_id", "email"])


def downgrade() -> None:
    op.drop_index("ix_org_invites_org_id_email", table_name="org_invites")
    op.drop_index("ix_org_invites_token_hash", table_name="org_invites")
    op.drop_table("org_invites")

    op.drop_index("ix_org_members_user_id", table_name="org_members")
    op.drop_index("ix_org_members_org_id", table_name="org_members")
    op.drop_table("org_members")
