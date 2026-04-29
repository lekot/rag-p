"""Security tests for the public YooKassa webhook endpoint.

Covers:
- IP allowlist (Caddy XFF chain + spoofing resistance).
- Server-side payment re-validation against ``GET /payments/{id}``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.main import app
from ragp_api.services.yookassa_client import PaymentRevalidationError
from ragp_api.settings import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_ORG = "org-test-001"
_PAYMENT_AMOUNT = "5.00"


def _webhook_payload(
    *,
    payment_id: str | None = None,
    org_id: str = _DEFAULT_ORG,
    amount: str = _PAYMENT_AMOUNT,
    currency: str = "RUB",
    event: str = "payment.succeeded",
    status: str = "succeeded",
) -> bytes:
    pid = payment_id or str(uuid.uuid4())
    return json.dumps(
        {
            "event": event,
            "object": {
                "id": pid,
                "status": status,
                "amount": {"value": amount, "currency": currency},
                "metadata": {
                    "org_id": org_id,
                    "amount_usd": "5.00",
                },
            },
        }
    ).encode()


def _authoritative(
    payment_id: str,
    *,
    status: str = "succeeded",
    amount: str = _PAYMENT_AMOUNT,
    currency: str = "RUB",
) -> dict[str, Any]:
    return {
        "id": payment_id,
        "status": status,
        "amount": {"value": amount, "currency": currency},
    }


@pytest_asyncio.fixture
async def make_client(
    db_engine: Any,
) -> AsyncIterator[Callable[[tuple[str, int]], Awaitable[AsyncClient]]]:
    """Factory yielding an AsyncClient pinned to a given peer (IP, port).

    Needed because the IP allowlist depends on ``request.client.host`` which is
    set by the ASGI transport per-instance, not per-request.
    """
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    fake_redis = FakeRedis()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    created: list[AsyncClient] = []

    async def _factory(peer: tuple[str, int]) -> AsyncClient:
        transport = ASGITransport(app=app, client=peer)
        ac = AsyncClient(transport=transport, base_url="http://test")
        created.append(ac)
        return ac

    try:
        yield _factory
    finally:
        for ac in created:
            await ac.aclose()
        app.dependency_overrides.clear()
        await fake_redis.aclose()


@pytest.fixture
def enable_ip_check():
    """Switch on the production-style IP allowlist for the duration of a test."""
    settings.yookassa_require_ip_check = True
    yield
    settings.yookassa_require_ip_check = False


@pytest.fixture
def enable_revalidation():
    """Switch on server-side payment re-validation."""
    settings.yookassa_revalidate_payment = True
    yield
    settings.yookassa_revalidate_payment = False


# ---------------------------------------------------------------------------
# IP allowlist tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_accepts_allowlisted_ip(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    enable_ip_check: None,
) -> None:
    """A request whose immediate peer is in the YooKassa CIDR is accepted.

    The handler may still 4xx because we feed it a synthetic body, but the IP
    dependency must let the request through (no 403)."""
    ac = await make_client(("185.71.76.5", 33421))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_webhook_rejects_disallowed_ip_403(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    enable_ip_check: None,
) -> None:
    """An attacker's POST from a random internet IP is rejected with 403."""
    ac = await make_client(("1.2.3.4", 12345))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "ip_not_allowed"


@pytest.mark.asyncio
async def test_webhook_uses_xff_when_caddy_is_trusted_proxy(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    enable_ip_check: None,
) -> None:
    """Caddy on the docker bridge is a trusted proxy — XFF is honoured."""
    ac = await make_client(("172.20.0.5", 80))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(),
        headers={
            "content-type": "application/json",
            # Real YooKassa IP, forwarded by trusted Caddy
            "x-forwarded-for": "185.71.76.5",
        },
    )
    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_webhook_ignores_xff_when_proxy_not_trusted(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    enable_ip_check: None,
) -> None:
    """Untrusted peer cannot whitelist itself by setting XFF.

    Peer is a public IP outside RAGP_YOOKASSA_TRUSTED_PROXIES, so the
    server falls back to the raw socket peer (1.2.3.4) and rejects the
    spoofed XFF claim of 185.71.76.5.
    """
    ac = await make_client(("1.2.3.4", 22222))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(),
        headers={
            "content-type": "application/json",
            "x-forwarded-for": "185.71.76.5",  # spoofed
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "ip_not_allowed"


@pytest.mark.asyncio
async def test_webhook_passes_when_ip_check_disabled(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    db_session: AsyncSession,
) -> None:
    """When RAGP_YOOKASSA_REQUIRE_IP_CHECK=false, all peers reach the handler.

    This is the default behaviour during the test suite (see conftest).
    """
    assert settings.yookassa_require_ip_check is False
    ac = await make_client(("1.2.3.4", 22222))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(payment_id=str(uuid.uuid4())),
        headers={"content-type": "application/json"},
    )
    # Topup logic runs and credits the org — definitely no 403 ip_not_allowed.
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_webhook_accepts_ipv6_allowlist(
    make_client: Callable[[tuple[str, int]], Awaitable[AsyncClient]],
    enable_ip_check: None,
) -> None:
    """IPv6 CIDR ``2a02:5180::/32`` is honoured (regression for IPv4-only matchers)."""
    ac = await make_client(("2a02:5180:0:1::1", 443))
    resp = await ac.post(
        "/api/v1/billing/webhook/yookassa",
        content=_webhook_payload(),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code != 403, resp.text


# ---------------------------------------------------------------------------
# Server-side re-validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_revalidation_rejects_fake_payment_id(
    client: AsyncClient,
    enable_revalidation: None,
) -> None:
    """Forged payment claim that YooKassa says was canceled -> 403."""
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(payment_id=payment_id)

    fake = AsyncMock(return_value=_authoritative(payment_id, status="canceled"))
    with patch(
        "ragp_api.api.v1.routes_billing.fetch_payment_status",
        new=fake,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "payment_revalidation_failed"
    fake.assert_awaited_once_with(payment_id)


@pytest.mark.asyncio
async def test_webhook_revalidation_rejects_amount_mismatch(
    client: AsyncClient,
    enable_revalidation: None,
) -> None:
    """Webhook claims amount=10000 RUB but YooKassa says 100 RUB -> 403."""
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(payment_id=payment_id, amount="10000.00")

    fake = AsyncMock(return_value=_authoritative(payment_id, amount="100.00"))
    with patch(
        "ragp_api.api.v1.routes_billing.fetch_payment_status",
        new=fake,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "payment_revalidation_failed"


@pytest.mark.asyncio
async def test_webhook_revalidation_rejects_currency_mismatch(
    client: AsyncClient,
    enable_revalidation: None,
) -> None:
    """Currency mismatch between webhook and authoritative source -> 403."""
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(payment_id=payment_id, currency="USD")

    fake = AsyncMock(return_value=_authoritative(payment_id, currency="RUB"))
    with patch(
        "ragp_api.api.v1.routes_billing.fetch_payment_status",
        new=fake,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "payment_revalidation_failed"


@pytest.mark.asyncio
async def test_webhook_revalidation_rejects_when_yookassa_unreachable(
    client: AsyncClient,
    enable_revalidation: None,
) -> None:
    """If YooKassa is unreachable we fail-closed: 403, not silent topup."""
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(payment_id=payment_id)

    with patch(
        "ragp_api.api.v1.routes_billing.fetch_payment_status",
        new=AsyncMock(side_effect=PaymentRevalidationError("network down")),
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "payment_revalidation_failed"


@pytest.mark.asyncio
async def test_webhook_passes_revalidation_with_matching_payment(
    client: AsyncClient,
    db_session: AsyncSession,
    enable_revalidation: None,
) -> None:
    """Happy path: webhook payload matches the authoritative payment object."""
    payment_id = str(uuid.uuid4())
    payload = _webhook_payload(payment_id=payment_id)

    fake = AsyncMock(return_value=_authoritative(payment_id))
    with patch(
        "ragp_api.api.v1.routes_billing.fetch_payment_status",
        new=fake,
    ):
        resp = await client.post(
            "/api/v1/billing/webhook/yookassa",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"
    fake.assert_awaited_once_with(payment_id)


# ---------------------------------------------------------------------------
# fetch_payment_status unit tests (cover retry + auth + transport errors)
# ---------------------------------------------------------------------------


def _patch_client_with_transport(transport: Any) -> Any:
    """Build a context-manager that swaps ``yookassa_client.httpx.AsyncClient``.

    We capture the *real* ``httpx.AsyncClient`` once (via module attribute lookup
    *before* the patch) so the substitute lambda can call it without recursing
    back into the mock.
    """
    import httpx

    real_async_client = httpx.AsyncClient

    def factory(*_args: Any, **_kwargs: Any) -> Any:
        return real_async_client(transport=transport)

    return patch("ragp_api.services.yookassa_client.httpx.AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_payment_status_returns_payment_object() -> None:
    """200 response with valid JSON is returned as-is."""
    import httpx

    from ragp_api.services import yookassa_client

    payment_id = "pmt-1"
    body = {
        "id": payment_id,
        "status": "succeeded",
        "amount": {"value": "100.00", "currency": "RUB"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/payments/{payment_id}")
        assert request.headers.get("authorization", "").startswith("Basic ")
        return httpx.Response(200, json=body)

    settings.yookassa_shop_id = "shop"
    settings.yookassa_secret_key = "secret"
    with _patch_client_with_transport(httpx.MockTransport(handler)):
        result = await yookassa_client.fetch_payment_status(payment_id)
    assert result == body


@pytest.mark.asyncio
async def test_fetch_payment_status_retries_on_5xx() -> None:
    """A 503 response triggers exactly one retry; the second 200 wins."""
    import httpx

    from ragp_api.services import yookassa_client

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": "x", "status": "succeeded", "amount": {}})

    settings.yookassa_shop_id = "shop"
    settings.yookassa_secret_key = "secret"
    with _patch_client_with_transport(httpx.MockTransport(handler)):
        result = await yookassa_client.fetch_payment_status("x")
    assert calls["n"] == 2
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_fetch_payment_status_raises_on_4xx() -> None:
    """A 401/404 is a fatal error — no retry, raise PaymentRevalidationError."""
    import httpx

    from ragp_api.services import yookassa_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"type": "error"})

    settings.yookassa_shop_id = "shop"
    settings.yookassa_secret_key = "secret"
    with (
        _patch_client_with_transport(httpx.MockTransport(handler)),
        pytest.raises(PaymentRevalidationError),
    ):
        await yookassa_client.fetch_payment_status("x")


@pytest.mark.asyncio
async def test_fetch_payment_status_requires_credentials() -> None:
    """Without shop_id + secret_key configured we refuse to call out at all."""
    from ragp_api.services import yookassa_client

    settings.yookassa_shop_id = ""
    settings.yookassa_secret_key = ""
    with pytest.raises(PaymentRevalidationError):
        await yookassa_client.fetch_payment_status("x")
