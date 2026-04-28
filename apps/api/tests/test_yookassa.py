"""Tests for YooKassa payment integration."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    BillingTransaction,
    OrgSubscription,
    Plan,
)
from ragp_api.services.fx import get_usd_to_rub_rate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMAIL = "owner@example.com"
_PASSWORD = "s3cr3t!"


async def _signup_and_login(
    client: AsyncClient,
    email: str = _EMAIL,
    org_name: str = "test-yookassa-org",
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": _PASSWORD, "organization_name": org_name},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    return data


def _make_payment_mock(
    payment_id: str = "22e12f66-000f-5000-8000-126628f15141",
    confirmation_url: str = "https://yoomoney.ru/checkout/payments/v2/contract?orderId=abc",
) -> MagicMock:
    """Build a mock that looks like a yookassa Payment object."""
    payment = MagicMock()
    payment.id = payment_id
    payment.confirmation = MagicMock()
    payment.confirmation.confirmation_url = confirmation_url
    return payment


def _webhook_payload(
    *,
    event: str = "payment.succeeded",
    payment_id: str = "22e12f66-000f-5000-8000-126628f15141",
    org_id: str = "org-test-001",
    amount_usd: str = "10.00",
) -> bytes:
    return json.dumps(
        {
            "event": event,
            "object": {
                "id": payment_id,
                "status": "succeeded",
                "metadata": {"org_id": org_id, "amount_usd": amount_usd},
            },
        }
    ).encode()


# ---------------------------------------------------------------------------
# FX service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usd_to_rub_rate_returns_cached_value() -> None:
    """When Redis has a cached value, CBR is not called."""
    redis = FakeRedis()
    await redis.set("fx:usd_rub", "90.5")

    with patch("ragp_api.services.fx.httpx.AsyncClient") as mock_client:
        rate = await get_usd_to_rub_rate(redis)

    assert rate == Decimal("90.5")
    mock_client.assert_not_called()
    await redis.aclose()


@pytest.mark.asyncio
async def test_get_usd_to_rub_rate_calls_cbr_on_cache_miss() -> None:
    """On cache miss, fetches from CBR and caches the result."""
    redis = FakeRedis()

    cbr_response = {"Valute": {"USD": {"Value": 88.25}}}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=cbr_response)

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(return_value=mock_resp)

    with patch("ragp_api.services.fx.httpx.AsyncClient", return_value=mock_http):
        rate = await get_usd_to_rub_rate(redis)

    assert rate == Decimal("88.25")

    # Verify it was cached
    cached = await redis.get("fx:usd_rub")
    assert cached is not None
    assert Decimal(cached.decode()) == Decimal("88.25")
    await redis.aclose()


@pytest.mark.asyncio
async def test_get_usd_to_rub_rate_falls_back_on_cbr_error() -> None:
    """On CBR error, returns fallback rate of 95."""
    redis = FakeRedis()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.get = AsyncMock(side_effect=Exception("CBR is down"))

    with patch("ragp_api.services.fx.httpx.AsyncClient", return_value=mock_http):
        rate = await get_usd_to_rub_rate(redis)

    assert rate == Decimal("95.0")
    await redis.aclose()


# ---------------------------------------------------------------------------
# Checkout endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checkout_requires_owner(
    client: AsyncClient,
) -> None:
    """Non-member of an org cannot create a checkout session — expects 403."""
    suffix = uuid.uuid4().hex[:6]

    # User A signs up (becomes owner of org-A)
    resp_a = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"owner-a-{suffix}@example.com",
            "password": _PASSWORD,
            "organization_name": f"OrgA-{suffix}",
        },
    )
    assert resp_a.status_code == 201, resp_a.text
    org_a_id = resp_a.json()["organization"]["id"]

    # User B signs up (owns org-B, not a member of org-A)
    resp_b = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"owner-b-{suffix}@example.com",
            "password": _PASSWORD,
            "organization_name": f"OrgB-{suffix}",
        },
    )
    assert resp_b.status_code == 201, resp_b.text

    # Login as user B
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": f"owner-b-{suffix}@example.com", "password": _PASSWORD},
    )
    assert login_resp.status_code == 200, login_resp.text

    # User B tries to create a checkout for org-A — not a member, expects 403
    resp = await client.post(
        f"/api/v1/orgs/{org_a_id}/billing/checkout",
        json={"amount_usd": "10.00"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_checkout_validates_amount_range(
    client: AsyncClient,
) -> None:
    """Amounts below $1 or above $1000 are rejected with 422."""
    # Signup and login as owner
    data = await _signup_and_login(
        client, email="checkout-val@example.com", org_name="checkout-val-org"
    )
    org_id = data.get("organization_id") or data.get("organization", {}).get("id", "")

    with patch("ragp_api.api.v1.routes_billing.create_payment") as mock_cp:
        mock_cp.return_value = ("pid", "https://yoomoney.ru/x", Decimal("95"))

        # Too small
        resp = await client.post(
            f"/api/v1/orgs/{org_id}/billing/checkout",
            json={"amount_usd": "0.50"},
        )
        assert resp.status_code == 422

        # Too large
        resp = await client.post(
            f"/api/v1/orgs/{org_id}/billing/checkout",
            json={"amount_usd": "2000.00"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_subscription_checkout_rejects_plan_below_used_storage(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    data = await _signup_and_login(
        client, email="subscription-storage@example.com", org_name="subscription-storage-org"
    )
    org_id = data.get("organization_id") or data.get("organization", {}).get("id", "")
    now = datetime.now(UTC)
    db_session.add(
        Plan(
            id="tiny-storage",
            name="Tiny Storage",
            price_rub_monthly=Decimal("100"),
            included_q=1000,
            included_storage_bytes=100,
            max_users=1,
            rpm_per_key=60,
            allow_overage=False,
            is_active=True,
            sort_order=1,
        )
    )
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="tiny-storage",
            status="active",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
            q_used=0,
            storage_bytes_used=200,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    with patch("ragp_api.api.v1.routes_billing.create_payment_rub") as mock_cp:
        resp = await client.post(
            f"/api/v1/orgs/{org_id}/subscription/checkout",
            json={"plan_id": "tiny-storage"},
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "storage_quota_exceeds_plan"
    mock_cp.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yookassa_webhook_payment_succeeded_tops_up_balance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """payment.succeeded webhook tops up the org balance."""
    org_id = "org-test-001"
    payment_id = str(uuid.uuid4())

    payload = _webhook_payload(org_id=org_id, amount_usd="5.00", payment_id=payment_id)

    resp = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["balance_usd"] == pytest.approx(5.0, abs=0.01)


@pytest.mark.asyncio
async def test_yookassa_webhook_idempotent_on_duplicate_payment_id(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sending the same webhook twice does not double-credit the balance."""
    org_id = "org-test-001"
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(org_id=org_id, amount_usd="3.00", payment_id=payment_id)

    # First call
    resp1 = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ok"

    # Second call — same payment_id
    resp2 = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "already_processed"

    # Balance should only be credited once
    result = await db_session.execute(
        select(BillingTransaction).where(
            BillingTransaction.reference_type == "yookassa_payment",
            BillingTransaction.reference_id == payment_id,
        )
    )
    txs = result.scalars().all()
    assert len(txs) == 1


@pytest.mark.asyncio
async def test_yookassa_webhook_ignores_unrelated_events(
    client: AsyncClient,
) -> None:
    """Events other than payment.succeeded are ignored (status=ignored)."""
    for event in ("payment.canceled", "refund.succeeded", "payment.waiting_for_capture"):
        payload = _webhook_payload(event=event)
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200, f"failed for event {event}"
        assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_yookassa_webhook_400_on_missing_metadata(
    client: AsyncClient,
) -> None:
    """Webhook without org_id/amount_usd in metadata returns 400."""
    payload = json.dumps(
        {
            "event": "payment.succeeded",
            "object": {
                "id": str(uuid.uuid4()),
                "status": "succeeded",
                "metadata": {},  # empty
            },
        }
    ).encode()

    resp = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
