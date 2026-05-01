"""Tests for transactional billing emails.

Covers:
- Each email helper logs a fallback line when SMTP_HOST is empty.
- Each email helper invokes aiosmtplib.send with the right To/Subject when SMTP is configured.
- YooKassa subscription webhook dispatches send_payment_received_email +
  send_subscription_activated_email exactly once on payment.succeeded, and
  records ``email.sent`` audit events.
- notify_subscription_lifecycle_task picks up expiring + expired subscriptions
  and dispatches the corresponding emails (idempotent per Redis key).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragp_api.db.models import (
    AuditEvent,
    Membership,
    Organization,
    OrgMember,
    OrgSubscription,
    Plan,
    User,
)
from ragp_api.services.email import (
    send_password_reset_email,
    send_payment_received_email,
    send_subscription_activated_email,
    send_subscription_expired_email,
    send_subscription_expiring_email,
)
from ragp_api.settings import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def patched_async_session(db_engine):
    """Redirect ragp_api.db.session.async_session at the test engine.

    The lifecycle cron opens its own DB session via ``async_session()``;
    without this patch the cron would hit the production DSN configured
    in ragp_api.settings.
    """
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("ragp_api.workers.tasks.async_session", factory),
        patch("ragp_api.db.session.async_session", factory),
    ):
        yield factory


async def _seed_org_with_owner(
    db: AsyncSession,
    *,
    org_id: str,
    email: str,
) -> str:
    """Create an org with one owner user.  Returns the user_id."""
    uid = str(uuid.uuid4())
    db.add(Organization(id=org_id, name=f"org-{org_id[:6]}", slug=f"slug-{org_id[:8]}"))
    db.add(User(id=uid, email=email, password_hash="x"))
    db.add(Membership(organization_id=org_id, user_id=uid, role="owner"))
    db.add(OrgMember(id=str(uuid.uuid4()), org_id=org_id, user_id=uid, role="owner"))
    await db.commit()
    return uid


async def _seed_plan(db: AsyncSession, plan_id: str = "personal") -> Plan:
    plan = Plan(
        id=plan_id,
        name="Personal",
        price_rub_monthly=Decimal("100"),
        included_q=1000,
        included_storage_bytes=10 * 1024 * 1024,
        max_users=1,
        rpm_per_key=60,
        allow_overage=False,
        is_active=True,
        sort_order=1,
    )
    db.add(plan)
    await db.commit()
    return plan


# ---------------------------------------------------------------------------
# email helper unit tests — logging fallback (smtp_host="")
# ---------------------------------------------------------------------------


@pytest.fixture
def smtp_disabled():
    """Ensure smtp_host is empty so helpers take the log fallback path."""
    saved = settings.smtp_host
    settings.smtp_host = ""
    yield
    settings.smtp_host = saved


@pytest.mark.asyncio
async def test_payment_received_email_logs_when_smtp_disabled(
    smtp_disabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ragp_api.services.email")
    await send_payment_received_email("alice@example.com", 499.0, "Personal")
    assert any("alice@example.com" in r.getMessage() for r in caplog.records)
    assert any("Personal" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_subscription_activated_email_logs_when_smtp_disabled(
    smtp_disabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ragp_api.services.email")
    await send_subscription_activated_email("bob@example.com", "Pro", "2026-06-01T00:00:00+00:00")
    assert any("bob@example.com" in r.getMessage() for r in caplog.records)
    assert any("Pro" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_subscription_expiring_email_logs_when_smtp_disabled(
    smtp_disabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ragp_api.services.email")
    await send_subscription_expiring_email(
        "carol@example.com", "Personal", "2026-05-04T00:00:00+00:00", 3
    )
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "carol@example.com" in msgs
    assert "Personal" in msgs
    assert "days_left=3" in msgs


@pytest.mark.asyncio
async def test_subscription_expired_email_logs_when_smtp_disabled(
    smtp_disabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ragp_api.services.email")
    await send_subscription_expired_email("dave@example.com", "Personal")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "dave@example.com" in msgs
    assert "Personal" in msgs


@pytest.mark.asyncio
async def test_password_reset_email_still_logs_when_smtp_disabled(
    smtp_disabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: refactor must not break the existing password-reset fallback."""
    caplog.set_level(logging.INFO, logger="ragp_api.services.email")
    await send_password_reset_email("legacy@example.com", "https://x/reset?t=abc")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "legacy@example.com" in msgs
    assert "https://x/reset?t=abc" in msgs


# ---------------------------------------------------------------------------
# email helper unit tests — aiosmtplib path (SMTP configured)
# ---------------------------------------------------------------------------


@pytest.fixture
def smtp_enabled():
    """Configure SMTP env so helpers exercise the aiosmtplib branch."""
    saved = (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_from,
    )
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_user = "noreply@example.com"
    settings.smtp_from = "noreply@example.com"
    yield
    (
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_user,
        settings.smtp_from,
    ) = saved


@pytest.mark.asyncio
async def test_payment_received_email_calls_aiosmtplib(smtp_enabled: None) -> None:
    fake_send = AsyncMock()
    with patch("aiosmtplib.send", new=fake_send):
        await send_payment_received_email("alice@example.com", 499.0, "Personal")
    fake_send.assert_awaited_once()
    msg = fake_send.await_args.args[0]
    assert msg["To"] == "alice@example.com"
    assert msg["Subject"] == "Платёж получен"


@pytest.mark.asyncio
async def test_subscription_activated_email_calls_aiosmtplib(smtp_enabled: None) -> None:
    fake_send = AsyncMock()
    with patch("aiosmtplib.send", new=fake_send):
        await send_subscription_activated_email(
            "bob@example.com", "Pro", "2026-06-01T00:00:00+00:00"
        )
    fake_send.assert_awaited_once()
    msg = fake_send.await_args.args[0]
    assert msg["To"] == "bob@example.com"
    assert msg["Subject"] == "Тариф активирован"


@pytest.mark.asyncio
async def test_subscription_expiring_email_calls_aiosmtplib(smtp_enabled: None) -> None:
    fake_send = AsyncMock()
    with patch("aiosmtplib.send", new=fake_send):
        await send_subscription_expiring_email(
            "carol@example.com", "Personal", "2026-05-04T00:00:00+00:00", 3
        )
    fake_send.assert_awaited_once()
    msg = fake_send.await_args.args[0]
    assert msg["To"] == "carol@example.com"
    assert msg["Subject"] == "Тариф скоро закончится"


@pytest.mark.asyncio
async def test_subscription_expired_email_calls_aiosmtplib(smtp_enabled: None) -> None:
    fake_send = AsyncMock()
    with patch("aiosmtplib.send", new=fake_send):
        await send_subscription_expired_email("dave@example.com", "Personal")
    fake_send.assert_awaited_once()
    msg = fake_send.await_args.args[0]
    assert msg["To"] == "dave@example.com"
    assert msg["Subject"] == "Тариф закончился"


# ---------------------------------------------------------------------------
# Webhook integration: payment.succeeded → emails dispatched
# ---------------------------------------------------------------------------


def _subscription_webhook_payload(
    *, payment_id: str, org_id: str, plan_id: str, amount_rub: str
) -> bytes:
    return json.dumps(
        {
            "event": "payment.succeeded",
            "object": {
                "id": payment_id,
                "status": "succeeded",
                "amount": {"value": amount_rub, "currency": "RUB"},
                "metadata": {
                    "org_id": org_id,
                    "plan_id": plan_id,
                    "type": "subscription",
                },
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_subscription_webhook_dispatches_emails(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A subscription payment.succeeded must call both email helpers exactly once."""
    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="webhook-owner@example.com")
    await _seed_plan(db_session, plan_id="personal")

    payment_id = str(uuid.uuid4())
    payload = _subscription_webhook_payload(
        payment_id=payment_id,
        org_id=org_id,
        plan_id="personal",
        amount_rub="100.00",
    )

    fake_payment = AsyncMock()
    fake_activated = AsyncMock()
    with (
        patch(
            "ragp_api.api.v1.routes_billing.send_payment_received_email",
            new=fake_payment,
        ),
        patch(
            "ragp_api.api.v1.routes_billing.send_subscription_activated_email",
            new=fake_activated,
        ),
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"

    fake_payment.assert_awaited_once()
    fake_activated.assert_awaited_once()
    # Positional args: (to, amount_rub, plan_name)
    pay_args = fake_payment.await_args.args
    assert pay_args[0] == "webhook-owner@example.com"
    assert pay_args[1] == 100.0
    assert pay_args[2] == "Personal"
    # Positional args: (to, plan_name, expires_at)
    act_args = fake_activated.await_args.args
    assert act_args[0] == "webhook-owner@example.com"
    assert act_args[1] == "Personal"

    # Audit events must include two email.sent rows.
    audit_rows = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "email.sent",
        )
    )
    kinds = {e.metadata_json.get("kind") for e in audit_rows.scalars().all()}
    assert kinds == {"payment_received", "subscription_activated"}


@pytest.mark.asyncio
async def test_subscription_webhook_email_failure_does_not_break_response(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """SMTP failure inside the webhook must not propagate to the response."""
    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="failer@example.com")
    await _seed_plan(db_session, plan_id="personal")

    payment_id = str(uuid.uuid4())
    payload = _subscription_webhook_payload(
        payment_id=payment_id,
        org_id=org_id,
        plan_id="personal",
        amount_rub="100.00",
    )

    boom = AsyncMock(side_effect=RuntimeError("smtp down"))
    with (
        patch("ragp_api.api.v1.routes_billing.send_payment_received_email", new=boom),
        patch("ragp_api.api.v1.routes_billing.send_subscription_activated_email", new=boom),
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Cron: notify_subscription_lifecycle_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_task_sends_expiring_email(
    db_session: AsyncSession,
    patched_async_session: Any,
) -> None:
    """An active subscription ending in <=3 days triggers the expiring email."""
    from ragp_api.workers import tasks as tasks_module

    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="expiring@example.com")
    await _seed_plan(db_session, plan_id="personal")

    now = datetime.now(UTC)
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="personal",
            status="active",
            current_period_start=now - timedelta(days=27),
            current_period_end=now + timedelta(days=2),  # within 3-day window
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    fake_expiring = AsyncMock()
    fake_expired = AsyncMock()
    fake_setnx = AsyncMock(return_value=True)  # first run: claim succeeds
    with (
        patch.object(tasks_module, "_redis_setnx_with_ttl", new=fake_setnx),
        patch(
            "ragp_api.services.email.send_subscription_expiring_email",
            new=fake_expiring,
        ),
        patch(
            "ragp_api.services.email.send_subscription_expired_email",
            new=fake_expired,
        ),
    ):
        result = await tasks_module.notify_subscription_lifecycle_task({})

    assert result == {"expiring": 1, "expired": 0}
    fake_expiring.assert_awaited_once()
    args = fake_expiring.await_args.args
    assert args[0] == "expiring@example.com"
    assert args[1] == "Personal"
    fake_expired.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle_task_sends_expired_email(
    db_session: AsyncSession,
    patched_async_session: Any,
) -> None:
    """A subscription that just transitioned to expired triggers the expired email."""
    from ragp_api.workers import tasks as tasks_module

    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="expired@example.com")
    await _seed_plan(db_session, plan_id="personal")

    now = datetime.now(UTC)
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="personal",
            status="expired",
            current_period_start=now - timedelta(days=31),
            current_period_end=now - timedelta(hours=2),  # ended within last 24h
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    fake_expiring = AsyncMock()
    fake_expired = AsyncMock()
    fake_setnx = AsyncMock(return_value=True)
    with (
        patch.object(tasks_module, "_redis_setnx_with_ttl", new=fake_setnx),
        patch(
            "ragp_api.services.email.send_subscription_expiring_email",
            new=fake_expiring,
        ),
        patch(
            "ragp_api.services.email.send_subscription_expired_email",
            new=fake_expired,
        ),
    ):
        result = await tasks_module.notify_subscription_lifecycle_task({})

    assert result == {"expiring": 0, "expired": 1}
    fake_expired.assert_awaited_once()
    args = fake_expired.await_args.args
    assert args[0] == "expired@example.com"
    assert args[1] == "Personal"
    fake_expiring.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle_task_idempotent_via_redis_setnx(
    db_session: AsyncSession,
    patched_async_session: Any,
) -> None:
    """When SETNX returns False (already-notified), no email is sent."""
    from ragp_api.workers import tasks as tasks_module

    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="dupe@example.com")
    await _seed_plan(db_session, plan_id="personal")

    now = datetime.now(UTC)
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="personal",
            status="active",
            current_period_start=now - timedelta(days=27),
            current_period_end=now + timedelta(days=2),
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    fake_expiring = AsyncMock()
    fake_setnx = AsyncMock(return_value=False)  # already claimed by previous run
    with (
        patch.object(tasks_module, "_redis_setnx_with_ttl", new=fake_setnx),
        patch(
            "ragp_api.services.email.send_subscription_expiring_email",
            new=fake_expiring,
        ),
    ):
        result = await tasks_module.notify_subscription_lifecycle_task({})

    assert result == {"expiring": 0, "expired": 0}
    fake_expiring.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle_task_records_audit_event_on_send(
    db_session: AsyncSession,
    patched_async_session: Any,
) -> None:
    """A successful expiring email writes an ``email.sent`` audit row."""
    from ragp_api.workers import tasks as tasks_module

    org_id = str(uuid.uuid4())
    await _seed_org_with_owner(db_session, org_id=org_id, email="audited@example.com")
    await _seed_plan(db_session, plan_id="personal")

    now = datetime.now(UTC)
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="personal",
            status="active",
            current_period_start=now - timedelta(days=27),
            current_period_end=now + timedelta(days=2),
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    fake_setnx = AsyncMock(return_value=True)
    with (
        patch.object(tasks_module, "_redis_setnx_with_ttl", new=fake_setnx),
        patch(
            "ragp_api.services.email.send_subscription_expiring_email",
            new=AsyncMock(),
        ),
    ):
        await tasks_module.notify_subscription_lifecycle_task({})

    rows = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "email.sent",
        )
    )
    events = rows.scalars().all()
    assert len(events) == 1
    metadata: dict[str, Any] = events[0].metadata_json
    assert metadata.get("kind") == "subscription_expiring"
    assert metadata.get("plan_id") == "personal"
