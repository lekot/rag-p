"""Tests for API key management endpoints."""

from __future__ import annotations

import hashlib

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup_and_login(
    client: AsyncClient,
    email: str = "keyuser@example.com",
    password: str = "passw0rd!",
    org_name: str = "keyorg",
) -> None:
    """Sign up (which also sets the session cookie on the client)."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": org_name},
    )
    assert resp.status_code == 201


async def _create_key(client: AsyncClient, name: str = "ci") -> dict:
    resp = await client.post("/api/v1/keys", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_key_returns_secret_once(client: AsyncClient) -> None:
    await _signup_and_login(client, email="k1@example.com", org_name="k1org")
    body = await _create_key(client, name="prod")

    assert "key" in body
    assert body["key"].startswith("rgp_")
    # "rgp_" (4) + 32 hex chars from os.urandom(16).hex()
    assert len(body["key"]) == 36
    assert body["key_prefix"] == body["key"][:8]
    assert body["name"] == "prod"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_keys_omits_secret(client: AsyncClient) -> None:
    await _signup_and_login(client, email="k2@example.com", org_name="k2org")
    await _create_key(client, name="mykey")

    resp = await client.get("/api/v1/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1
    for k in keys:
        assert "key" not in k  # full secret must never appear in list
        assert "key_prefix" in k
        assert "name" in k
        assert "id" in k


@pytest.mark.asyncio
async def test_api_key_auth_works_for_protected_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Create a key via session, then verify the key_hash is correctly stored
    and that get_api_key_org resolves the org from the Bearer token."""
    from unittest.mock import MagicMock

    await _signup_and_login(client, email="k3@example.com", org_name="k3org")
    key_body = await _create_key(client, name="bearer-test")
    raw_key = key_body["key"]

    # Verify the key is in DB with correct hash
    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    result = await db_session.execute(select(ApiKey).where(ApiKey.key_hash == expected_hash))
    stored_key = result.scalar_one_or_none()
    assert stored_key is not None
    assert stored_key.name == "bearer-test"
    assert stored_key.key_prefix == raw_key[:8]

    # Verify get_api_key_org resolves the org from Bearer header using the same DB
    from ragp_api.deps_auth import get_api_key_org

    mock_request = MagicMock()
    mock_request.headers = {"Authorization": f"Bearer {raw_key}"}
    mock_request.cookies = {}

    result_tuple = await get_api_key_org(mock_request, db_session)
    assert result_tuple is not None
    org, api_key = result_tuple
    assert org.id == stored_key.organization_id
    assert api_key.id == stored_key.id

    # Confirm the key appears in the authenticated user's key list
    list_resp = await client.get("/api/v1/keys")
    assert list_resp.status_code == 200
    names = [k["name"] for k in list_resp.json()]
    assert "bearer-test" in names
