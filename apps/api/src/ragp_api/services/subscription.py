"""Subscription service — quota-based billing lifecycle.

Manages plan subscriptions, quota consumption, renewal, and expiry.
All balance mutations use SELECT FOR UPDATE on PostgreSQL to prevent races.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgSubscription, Plan, SubscriptionEvent

logger = logging.getLogger(__name__)

_PERIOD_DAYS = 30


def _aware_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC-aware so comparisons never raise.

    Why: SQLAlchemy + some DB drivers (e.g. SQLite, certain Postgres async paths)
    can return tz-naive datetimes from columns declared TIMESTAMP WITH TIME ZONE.
    Comparing those with `datetime.now(UTC)` raises TypeError. Coerce on read.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class NoActiveSubscriptionError(Exception):
    """Raised when an operation requires an active subscription but none exists."""


class QuotaExceededError(Exception):
    """Raised when q_used would exceed included_q on a plan without overage."""

    def __init__(self, q_used: int, q_limit: int) -> None:
        self.q_used = q_used
        self.q_limit = q_limit
        super().__init__(f"Query quota exceeded: {q_used}/{q_limit}")


class StorageQuotaExceededError(Exception):
    """Raised when storage_bytes_used would exceed included_storage_bytes."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(f"Storage quota exceeded: {used}/{limit}")


@dataclass(frozen=True)
class QuotaConsumption:
    """Result of a successful query quota reservation."""

    q_used: int
    q_limit: int | None
    overage: bool


async def has_active_subscription(db: AsyncSession, org_id: str) -> bool:
    """Return True iff the org currently has an active, non-expired subscription.

    Read-only, side-effect free probe used by /auth/me, /auth/signup and
    /auth/login responses to drive the post-signup customer-journey UX.
    Unlike :func:`get_active_subscription`, this helper does NOT mutate the
    row when the period has elapsed — it simply returns False.
    """
    result = await db.execute(
        select(OrgSubscription.id).where(
            OrgSubscription.org_id == org_id,
            OrgSubscription.status == "active",
            OrgSubscription.current_period_end > datetime.now(UTC),
        )
    )
    return result.first() is not None


async def get_active_subscription(db: AsyncSession, org_id: str) -> OrgSubscription | None:
    """Return the active subscription for *org_id*.

    Lazily expires the row if current_period_end < now() and returns None.
    """
    result = await db.execute(select(OrgSubscription).where(OrgSubscription.org_id == org_id))
    sub = result.scalar_one_or_none()
    if sub is None:
        return None

    # Lazy expiry check
    if sub.status == "active" and _aware_utc(sub.current_period_end) < datetime.now(UTC):
        sub.status = "expired"
        sub.updated_at = datetime.now(UTC)
        _log_event(
            db,
            org_id=org_id,
            plan_id=sub.plan_id,
            event_type="expired",
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
        )
        await db.flush()
        return None

    if sub.status != "active":
        return None

    return sub


def _log_event(
    db: AsyncSession,
    *,
    org_id: str,
    plan_id: str,
    event_type: str,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    yookassa_payment_id: str | None = None,
    amount_rub: Decimal | None = None,
) -> SubscriptionEvent:
    """Create a SubscriptionEvent row and add it to the session (no flush)."""
    ev = SubscriptionEvent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        plan_id=plan_id,
        event_type=event_type,
        period_start=period_start,
        period_end=period_end,
        yookassa_payment_id=yookassa_payment_id,
        amount_rub=amount_rub,
        created_at=datetime.now(UTC),
    )
    db.add(ev)
    return ev


async def consume_q(db: AsyncSession, org_id: str, count: int = 1) -> QuotaConsumption:
    """Atomically increment q_used by *count*.

    Raises NoActiveSubscriptionError if no active subscription exists.
    Raises QuotaExceededError if q_used + count > included_q and plan
    does not allow overage.
    """
    result = await db.execute(
        select(OrgSubscription).where(OrgSubscription.org_id == org_id).with_for_update()
    )
    sub = result.scalar_one_or_none()

    if sub is None or sub.status != "active":
        raise NoActiveSubscriptionError(f"No active subscription for org {org_id}")

    if _aware_utc(sub.current_period_end) < datetime.now(UTC):
        sub.status = "expired"
        sub.updated_at = datetime.now(UTC)
        await db.flush()
        raise NoActiveSubscriptionError(f"Subscription expired for org {org_id}")

    # Load plan to check overage policy
    plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    plan = plan_result.scalar_one_or_none()

    q_limit = plan.included_q if plan is not None else None
    if plan is not None and not plan.allow_overage and sub.q_used + count > plan.included_q:
        raise QuotaExceededError(q_used=sub.q_used, q_limit=plan.included_q)

    sub.q_used = sub.q_used + count
    sub.updated_at = datetime.now(UTC)
    await db.flush()
    return QuotaConsumption(
        q_used=sub.q_used,
        q_limit=q_limit,
        overage=bool(plan is not None and plan.allow_overage and sub.q_used > plan.included_q),
    )


async def release_q(db: AsyncSession, org_id: str, count: int = 1) -> None:
    """Release a previously reserved query quota slot.

    This is used when a RAG request reserved quota but failed before producing
    a billable answer. It is best-effort and never raises if the subscription
    row disappeared.
    """
    result = await db.execute(
        select(OrgSubscription).where(OrgSubscription.org_id == org_id).with_for_update()
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return

    sub.q_used = max(0, sub.q_used - count)
    sub.updated_at = datetime.now(UTC)
    await db.flush()


async def consume_storage(db: AsyncSession, org_id: str, bytes_count: int) -> None:
    """Increment storage_bytes_used by *bytes_count*.

    Raises NoActiveSubscriptionError if no active subscription.
    Raises StorageQuotaExceededError if would exceed included_storage_bytes.
    """
    result = await db.execute(
        select(OrgSubscription).where(OrgSubscription.org_id == org_id).with_for_update()
    )
    sub = result.scalar_one_or_none()

    if sub is None or sub.status != "active":
        raise NoActiveSubscriptionError(f"No active subscription for org {org_id}")

    if _aware_utc(sub.current_period_end) < datetime.now(UTC):
        sub.status = "expired"
        sub.updated_at = datetime.now(UTC)
        await db.flush()
        raise NoActiveSubscriptionError(f"Subscription expired for org {org_id}")

    plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    plan = plan_result.scalar_one_or_none()

    if plan is not None and sub.storage_bytes_used + bytes_count > plan.included_storage_bytes:
        raise StorageQuotaExceededError(
            used=sub.storage_bytes_used, limit=plan.included_storage_bytes
        )

    sub.storage_bytes_used = sub.storage_bytes_used + bytes_count
    sub.updated_at = datetime.now(UTC)
    await db.flush()


async def release_storage(db: AsyncSession, org_id: str, bytes_count: int) -> None:
    """Decrement storage_bytes_used by *bytes_count* (called on dataset deletion)."""
    result = await db.execute(
        select(OrgSubscription).where(OrgSubscription.org_id == org_id).with_for_update()
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return

    sub.storage_bytes_used = max(0, sub.storage_bytes_used - bytes_count)
    sub.updated_at = datetime.now(UTC)
    await db.flush()


async def start_subscription(
    db: AsyncSession,
    *,
    org_id: str,
    plan_id: str,
    payment_id: str,
    amount_rub: Decimal,
) -> OrgSubscription:
    """Create or renew a subscription for *org_id*.

    Rules:
    - No existing active → create new with 30d period.
    - Same plan, active → renewal: period_end += 30d, q_used = 0,
      storage_bytes_used preserved, period_end = max(now, period_end) + 30d.
    - Different plan (upgrade or downgrade) → switch plan in-place, reset query usage,
      preserve storage usage.
    """
    # Verify plan exists
    plan_result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan_id}")

    now = datetime.now(UTC)

    # Check existing subscription
    result = await db.execute(
        select(OrgSubscription).where(OrgSubscription.org_id == org_id).with_for_update()
    )
    sub = result.scalar_one_or_none()

    if sub is not None and sub.status == "active" and _aware_utc(sub.current_period_end) >= now:
        if sub.plan_id == plan_id:
            # ---- Renewal ----
            new_end = max(now, _aware_utc(sub.current_period_end)) + timedelta(days=_PERIOD_DAYS)
            sub.current_period_end = new_end
            sub.q_used = 0
            sub.updated_at = now
            _log_event(
                db,
                org_id=org_id,
                plan_id=plan_id,
                event_type="renewed",
                period_start=sub.current_period_start,
                period_end=new_end,
                yookassa_payment_id=payment_id,
                amount_rub=amount_rub,
            )
        else:
            # ---- Upgrade / downgrade ----
            old_plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
            old_plan = old_plan_result.scalar_one_or_none()
            event_type = (
                "upgraded"
                if (old_plan is None or plan.price_rub_monthly > old_plan.price_rub_monthly)
                else "downgraded"
            )
            old_period_start = sub.current_period_start
            old_period_end = sub.current_period_end
            old_plan_id = sub.plan_id
            _log_event(
                db,
                org_id=org_id,
                plan_id=old_plan_id,
                event_type="cancelled",
                period_start=old_period_start,
                period_end=old_period_end,
            )

            # Keep the 1:1 org row and switch it in-place. Creating a second
            # row violates the unique org_id constraint under PostgreSQL.
            period_end = now + timedelta(days=_PERIOD_DAYS)
            sub.plan_id = plan_id
            sub.status = "active"
            sub.current_period_start = now
            sub.current_period_end = period_end
            sub.q_used = 0
            sub.auto_renew = False
            sub.updated_at = now
            _log_event(
                db,
                org_id=org_id,
                plan_id=plan_id,
                event_type=event_type,
                period_start=now,
                period_end=period_end,
                yookassa_payment_id=payment_id,
                amount_rub=amount_rub,
            )
    else:
        # ---- New subscription (or re-subscribe after expiry) ----
        period_end = now + timedelta(days=_PERIOD_DAYS)
        if sub is not None:
            # Update existing (expired/cancelled) row in-place
            sub.plan_id = plan_id
            sub.status = "active"
            sub.current_period_start = now
            sub.current_period_end = period_end
            sub.q_used = 0
            sub.auto_renew = False
            sub.updated_at = now
        else:
            sub = OrgSubscription(
                id=str(uuid.uuid4()),
                org_id=org_id,
                plan_id=plan_id,
                status="active",
                current_period_start=now,
                current_period_end=period_end,
                q_used=0,
                storage_bytes_used=0,
                auto_renew=False,
                created_at=now,
                updated_at=now,
            )
            db.add(sub)
        _log_event(
            db,
            org_id=org_id,
            plan_id=plan_id,
            event_type="started",
            period_start=now,
            period_end=period_end,
            yookassa_payment_id=payment_id,
            amount_rub=amount_rub,
        )

    await db.flush()
    return sub


async def expire_old_subscriptions(db: AsyncSession) -> int:
    """Cron task: mark expired all subscriptions where current_period_end < now().

    Returns the number of subscriptions expired.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(OrgSubscription).where(
            OrgSubscription.status == "active",
            OrgSubscription.current_period_end < now,
        )
    )
    subs = result.scalars().all()
    count = 0
    for sub in subs:
        sub.status = "expired"
        sub.updated_at = now
        _log_event(
            db,
            org_id=sub.org_id,
            plan_id=sub.plan_id,
            event_type="expired",
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
        )
        count += 1
    await db.flush()
    return count
