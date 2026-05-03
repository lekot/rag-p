import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ragp_api.db.base import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class MembershipRole(str, PyEnum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"


class OrgRole(str, PyEnum):
    owner = "owner"
    admin = "admin"
    member = "member"


class InviteRole(str, PyEnum):
    admin = "admin"
    member = "member"


class DatasetSource(str, PyEnum):
    uploaded = "uploaded"
    generated = "generated"


class RunStatus(str, PyEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ExperimentStatus(str, PyEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization")
    pipelines: Mapped[list["Pipeline"]] = relationship(back_populates="organization")
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="organization")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="organization")
    org_members: Mapped[list["OrgMember"]] = relationship(back_populates="organization")
    org_invites: Mapped[list["OrgInvite"]] = relationship(back_populates="organization")
    balance: Mapped["OrgBalance | None"] = relationship(
        back_populates="organization", uselist=False
    )
    billing_transactions: Mapped[list["BillingTransaction"]] = relationship(
        back_populates="organization"
    )
    subscription: Mapped["OrgSubscription | None"] = relationship(
        back_populates="organization", uselist=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bumped on password reset so pre-reset cookies are rejected.
    sessions_invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")
    org_members: Mapped[list["OrgMember"]] = relationship(back_populates="user")
    sent_invites: Mapped[list["OrgInvite"]] = relationship(
        back_populates="inviter", foreign_keys="OrgInvite.invited_by"
    )


class Membership(Base):
    __tablename__ = "memberships"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class OrgMember(Base):
    """Multi-user org membership with roles: owner / admin / member."""

    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="org_members")
    user: Mapped["User"] = relationship(back_populates="org_members")


class OrgInvite(Base):
    """Pending invite to join an org."""

    __tablename__ = "org_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="org_invites")
    inviter: Mapped["User"] = relationship(back_populates="sent_invites", foreign_keys=[invited_by])


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="pipelines")
    versions: Mapped[list["PipelineVersion"]] = relationship(
        back_populates="pipeline", foreign_keys="PipelineVersion.pipeline_id"
    )


class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    pipeline_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipelines.id"), nullable=False)
    nodes_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship(
        back_populates="versions", foreign_keys=[pipeline_id]
    )


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="datasets")
    items: Mapped[list["DatasetItem"]] = relationship(back_populates="dataset")
    golden_items: Mapped[list["DatasetGoldenItem"]] = relationship(back_populates="dataset")


class DatasetItem(Base):
    __tablename__ = "dataset_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    golden_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    golden_contexts_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="items")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id"), nullable=True
    )
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    raw_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="transient")
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    pipeline_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_versions.id"), nullable=False
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id"), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    traces_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    plugin_grid_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    leaderboard_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Watchdog heartbeat: bumped on every commit inside run_experiment_inline so
    # the stale-experiment cron can detect dead workers.  ``onupdate`` updates
    # the column automatically whenever any other column on the row is changed,
    # but the runner also touches it explicitly to handle no-op commits.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DatasetGoldenItem(Base):
    __tablename__ = "dataset_golden_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship(back_populates="golden_items")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")
    user: Mapped["User"] = relationship(back_populates="api_keys")


class UsageEvent(Base):
    """Raw per-request usage record."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class UsageDaily(Base):
    """Daily aggregated usage per org + model."""

    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("org_id", "day", "model", name="uq_usage_daily_org_day_model"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    total_prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuditEvent(Base):
    """Audit log entry for security-relevant actions."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Plan(Base):
    """Subscription plan catalogue (static seed data)."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    price_rub_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    included_q: Mapped[int] = mapped_column(BigInteger, nullable=False)
    included_storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False)
    rpm_per_key: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_overage: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrgSubscription(Base):
    """Active subscription for an organization (1:1 with organizations)."""

    __tablename__ = "org_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False, unique=True
    )
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id"), nullable=False)
    # 'active' | 'expired' | 'cancelled'
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    q_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_bytes_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # MVP: always false — renewal is manual
    auto_renew: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="subscription")
    plan: Mapped["Plan"] = relationship()


class SubscriptionEvent(Base):
    """History of subscription lifecycle events."""

    __tablename__ = "subscription_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    __table_args__ = (
        UniqueConstraint("yookassa_payment_id", name="uq_subscription_events_yookassa_payment_id"),
    )

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(32), ForeignKey("plans.id"), nullable=False)
    # 'started' | 'renewed' | 'expired' | 'cancelled' | 'upgraded' | 'downgraded'
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    yookassa_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_rub: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgBalance(Base):
    """Overage wallet for an organization — used by Corp/Enterprise for agreed overages.

    For subscription-based billing this is only charged when q_used exceeds
    included_q on a plan with allow_overage=True.
    """

    __tablename__ = "org_balances"

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="balance")


class BillingTransaction(Base):
    """Record of every balance change (topup / deduction / starting_credit)."""

    __tablename__ = "billing_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    # 'topup' | 'deduction' | 'starting_credit'
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # always a positive value; sign is conveyed by type
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    balance_after_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    # 'usage_event' | 'manual_topup' | 'system'
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="billing_transactions")


class PasswordResetToken(Base):
    """Single-use password reset token (sha256 hash stored, never raw)."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
