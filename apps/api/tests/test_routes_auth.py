"""Tests for authentication endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgSubscription, Plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str = "alice@example.com",
    password: str = "s3cr3t!",
    organization_name: str | None = "acme",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": organization_name},
    )
    return resp


async def _login(
    client: AsyncClient,
    email: str = "alice@example.com",
    password: str = "s3cr3t!",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_creates_user_org_membership(client: AsyncClient) -> None:
    resp = await _signup(client)
    assert resp.status_code == 201
    body = resp.json()
    assert "user" in body
    assert "organization" in body
    assert body["user"]["email"] == "alice@example.com"
    assert body["organization"]["role"] == "owner"
    assert body["organization"]["slug"] == "acme"
    # Session cookie must be set
    assert "ragp_session" in resp.cookies


@pytest.mark.asyncio
async def test_signup_duplicate_email_409(client: AsyncClient) -> None:
    await _signup(client, email="dup@example.com")
    resp = await _signup(client, email="dup@example.com")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password_401(client: AsyncClient) -> None:
    await _signup(client, email="bob@example.com", password="correct!")
    resp = await _login(client, email="bob@example.com", password="wrong!")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_without_cookie_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_cookie_returns_user_org(client: AsyncClient) -> None:
    signup_resp = await _signup(client, email="carol@example.com")
    assert signup_resp.status_code == 201
    # httpx AsyncClient preserves cookies across requests in the same client
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["user"]["email"] == "carol@example.com"
    assert body["organization"]["role"] == "owner"


# ---------------------------------------------------------------------------
# has_active_subscription flag in auth responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_returns_has_active_subscription_false(client: AsyncClient) -> None:
    """A brand-new account has no subscription — the response must signal
    that explicitly so the web app redirects to /pricing."""
    resp = await _signup(client, email="journey-signup@example.com", organization_name="JourneyOrg")
    assert resp.status_code == 201
    body = resp.json()
    assert "has_active_subscription" in body
    assert body["has_active_subscription"] is False


@pytest.mark.asyncio
async def test_me_endpoint_includes_subscription_flag(client: AsyncClient) -> None:
    """GET /auth/me returns has_active_subscription=False after signup
    (no OrgSubscription is created on signup)."""
    signup_resp = await _signup(
        client, email="journey-me@example.com", organization_name="JourneyMeOrg"
    )
    assert signup_resp.status_code == 201

    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert "has_active_subscription" in body
    assert body["has_active_subscription"] is False


@pytest.mark.asyncio
async def test_login_includes_subscription_flag_for_active_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Login response reflects an existing active subscription as True."""
    signup_resp = await _signup(
        client, email="journey-login@example.com", organization_name="JourneyLoginOrg"
    )
    assert signup_resp.status_code == 201
    org_id = signup_resp.json()["organization"]["id"]

    # Seed an active plan + subscription directly
    plan = Plan(
        id="personal",
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
    db_session.add(plan)
    now = datetime.now(UTC)
    sub = OrgSubscription(
        id=str(uuid.uuid4()),
        org_id=org_id,
        plan_id="personal",
        status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29),
        q_used=0,
        storage_bytes_used=0,
        auto_renew=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(sub)
    await db_session.commit()

    login_resp = await _login(client, email="journey-login@example.com")
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["has_active_subscription"] is True


@pytest.mark.asyncio
async def test_logout_clears_cookie(client: AsyncClient) -> None:
    await _signup(client, email="dan@example.com")
    # Verify /me works before logout
    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200

    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 204

    # After logout cookie is cleared — /me should 401
    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code == 401
