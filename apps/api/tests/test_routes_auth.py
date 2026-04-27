"""Tests for authentication endpoints."""

import pytest
from httpx import AsyncClient

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
