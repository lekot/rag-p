"""Tests for subscription lifecycle and quota accounting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgSubscription, Plan, SubscriptionEvent
from ragp_api.services.subscription import (
    NoActiveSubscriptionError,
    consume_storage,
    start_subscription,
)


async def _seed_plan(
    db: AsyncSession,
    *,
    plan_id: str,
    price_rub: Decimal,
    included_q: int = 100,
    included_storage_bytes: int = 1024,
    allow_overage: bool = False,
) -> None:
    db.add(
        Plan(
            id=plan_id,
            name=plan_id.title(),
            price_rub_monthly=price_rub,
            included_q=included_q,
            included_storage_bytes=included_storage_bytes,
            max_users=1,
            rpm_per_key=60,
            allow_overage=allow_overage,
            is_active=True,
            sort_order=1,
        )
    )


@pytest.mark.asyncio
async def test_plan_switch_updates_existing_subscription_row(
    db_session: AsyncSession,
) -> None:
    """Changing plan must not create a second row for the same org_id."""
    org_id = "org-test-001"
    now = datetime.now(UTC)
    await _seed_plan(db_session, plan_id="personal", price_rub=Decimal("100"))
    await _seed_plan(db_session, plan_id="pro", price_rub=Decimal("1500"))
    sub = OrgSubscription(
        id=str(uuid.uuid4()),
        org_id=org_id,
        plan_id="personal",
        status="active",
        current_period_start=now - timedelta(days=5),
        current_period_end=now + timedelta(days=25),
        q_used=42,
        storage_bytes_used=512,
        auto_renew=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(sub)
    await db_session.commit()

    switched = await start_subscription(
        db_session,
        org_id=org_id,
        plan_id="pro",
        payment_id="pay_plan_switch",
        amount_rub=Decimal("1500"),
    )
    await db_session.commit()

    assert switched.id == sub.id
    assert switched.plan_id == "pro"
    assert switched.status == "active"
    assert switched.q_used == 0
    assert switched.storage_bytes_used == 0

    rows = (
        await db_session.execute(
            select(OrgSubscription).where(OrgSubscription.org_id == org_id)
        )
    ).scalars().all()
    assert len(rows) == 1

    events = (
        await db_session.execute(
            select(SubscriptionEvent.event_type).where(
                SubscriptionEvent.org_id == org_id
            )
        )
    ).scalars().all()
    assert events == ["cancelled", "upgraded"]


@pytest.mark.asyncio
async def test_consume_storage_expires_stale_active_subscription(
    db_session: AsyncSession,
) -> None:
    org_id = "org-test-001"
    now = datetime.now(UTC)
    await _seed_plan(db_session, plan_id="personal", price_rub=Decimal("100"))
    sub = OrgSubscription(
        id=str(uuid.uuid4()),
        org_id=org_id,
        plan_id="personal",
        status="active",
        current_period_start=now - timedelta(days=35),
        current_period_end=now - timedelta(days=5),
        q_used=0,
        storage_bytes_used=0,
        auto_renew=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(sub)
    await db_session.commit()

    with pytest.raises(NoActiveSubscriptionError):
        await consume_storage(db_session, org_id, 10)

    assert sub.status == "expired"
