"""Tests for org members and invites endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgInvite, OrgMember
from ragp_api.deps_auth import COOKIE_NAME

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str,
    password: str = "s3cr3t!",
    org_name: str | None = None,
) -> dict:
    body: dict = {"email": email, "password": password}
    if org_name:
        body["organization_name"] = org_name
    resp = await client.post("/api/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str = "s3cr3t!") -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_org_member(
    db_session: AsyncSession,
    org_id: str,
    user_id: str,
    role: str,
) -> None:
    """Directly insert an OrgMember row (bypass routes)."""
    await db_session.execute(
        insert(OrgMember).values(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            role=role,
        )
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_creates_record_and_returns_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Owner creates an invite — response contains invite_url."""
    data = await _signup(client, "owner@example.com", org_name="acme")
    org_id = data["organization"]["id"]

    # Owner is already a session user via signup cookie
    resp = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "newbie@example.com", "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "invite_url" in body
    assert "lekottt.ru/invite/" in body["invite_url"]
    assert body["id"]


@pytest.mark.asyncio
async def test_accept_invite_adds_member_with_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Signed-in user accepts an invite and gets added with correct role."""
    owner_data = await _signup(client, "owner2@example.com", org_name="corp")
    org_id = owner_data["organization"]["id"]

    invite_resp = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "joiner@example.com", "role": "member"},
    )
    assert invite_resp.status_code == 201
    invite_url = invite_resp.json()["invite_url"]
    raw_token = invite_url.split("/invite/")[-1]

    dataset_resp = await client.post(
        "/api/v1/datasets",
        json={"name": "Shared Corp Dataset"},
    )
    assert dataset_resp.status_code == 201, dataset_resp.text
    dataset_id = dataset_resp.json()["id"]

    # Sign up as the invitee (creates their own org, but we'll accept the invite)
    await client.post("/api/v1/auth/logout")

    await _signup(client, "joiner@example.com", org_name="joiner-org")

    # Accept invite
    accept_resp = await client.post("/api/v1/invites/accept", json={"token": raw_token})
    assert accept_resp.status_code == 200, accept_resp.text
    body = accept_resp.json()
    assert body["org_id"] == org_id
    assert body["role"] == "member"

    me_resp = await client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200, me_resp.text
    assert me_resp.json()["organization"]["id"] == org_id

    datasets_resp = await client.get("/api/v1/datasets")
    assert datasets_resp.status_code == 200, datasets_resp.text
    assert [d["id"] for d in datasets_resp.json()] == [dataset_id]

    # Verify via list members (need to log back as owner)
    await client.post("/api/v1/auth/logout")
    await _login(client, "owner2@example.com")

    members_resp = await client.get(f"/api/v1/orgs/{org_id}/members")
    assert members_resp.status_code == 200, members_resp.text
    emails = [m["email"] for m in members_resp.json()]
    assert "joiner@example.com" in emails


@pytest.mark.asyncio
async def test_same_named_signup_creates_separate_organizations(
    client: AsyncClient,
) -> None:
    """Same organization display names do not imply shared tenant scope."""
    first = await _signup(client, "same-name-a@example.com", org_name="Same Name LLC")
    first_org_id = first["organization"]["id"]

    dataset_resp = await client.post(
        "/api/v1/datasets",
        json={"name": "First tenant dataset"},
    )
    assert dataset_resp.status_code == 201, dataset_resp.text

    await client.post("/api/v1/auth/logout")

    second = await _signup(client, "same-name-b@example.com", org_name="Same Name LLC")
    second_org_id = second["organization"]["id"]

    assert second_org_id != first_org_id
    assert second["organization"]["slug"] != first["organization"]["slug"]

    datasets_resp = await client.get("/api/v1/datasets")
    assert datasets_resp.status_code == 200, datasets_resp.text
    assert datasets_resp.json() == []


@pytest.mark.asyncio
async def test_member_cannot_invite(client: AsyncClient, db_session: AsyncSession) -> None:
    """A plain member gets 403 when trying to invite someone."""
    owner_data = await _signup(client, "owner3@example.com", org_name="firm3")
    org_id = owner_data["organization"]["id"]

    # Create member user and add to org
    member_data = await _signup(client, "member3@example.com", org_name="personal3")
    member_user_id = member_data["user"]["id"]
    await _seed_org_member(db_session, org_id, member_user_id, "member")

    # Log in as member
    await client.post("/api/v1/auth/logout")
    await _login(client, "member3@example.com")

    resp = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "another@example.com", "role": "member"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_admin_can_invite_member_but_not_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Admin can invite a member but cannot invite another admin."""
    owner_data = await _signup(client, "owner4@example.com", org_name="firm4")
    org_id = owner_data["organization"]["id"]

    admin_data = await _signup(client, "admin4@example.com", org_name="personal4")
    admin_user_id = admin_data["user"]["id"]
    await _seed_org_member(db_session, org_id, admin_user_id, "admin")

    await client.post("/api/v1/auth/logout")
    await _login(client, "admin4@example.com")

    # Can invite member
    resp_member = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "newmember4@example.com", "role": "member"},
    )
    assert resp_member.status_code == 201, resp_member.text

    # Cannot invite admin
    resp_admin = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "newadmin4@example.com", "role": "admin"},
    )
    assert resp_admin.status_code == 403, resp_admin.text


@pytest.mark.asyncio
async def test_owner_cannot_remove_self_if_last_owner(
    client: AsyncClient,
) -> None:
    """Owner cannot remove themselves when they're the last owner."""
    owner_data = await _signup(client, "owner5@example.com", org_name="firm5")
    org_id = owner_data["organization"]["id"]
    user_id = owner_data["user"]["id"]

    # signup already seeds org_member with role=owner
    resp = await client.delete(f"/api/v1/orgs/{org_id}/members/{user_id}")
    assert resp.status_code == 400, resp.text
    assert "last owner" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invite_expires_after_7_days(client: AsyncClient, db_session: AsyncSession) -> None:
    """An expired invite cannot be accepted."""
    owner_data = await _signup(client, "owner6@example.com", org_name="firm6")
    org_id = owner_data["organization"]["id"]
    owner_user_id = owner_data["user"]["id"]

    # Create a second user who will try to accept the expired invite
    await _signup(client, "joiner6@example.com", org_name="joiner-org6")

    # Seed expired invite directly (for joiner6)
    raw_token = "expired-token-abc123-unique6"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)
    expired_invite = OrgInvite(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email="joiner6@example.com",
        role="member",
        token_hash=token_hash,
        invited_by=owner_user_id,
        created_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1),
        accepted_at=None,
    )
    db_session.add(expired_invite)
    await db_session.commit()

    # joiner6 is already logged in after _signup above — try to accept expired invite
    # (joiner6 is not yet a member of org_id, so the "already a member" check won't block us)
    resp = await client.post("/api/v1/invites/accept", json={"token": raw_token})
    assert resp.status_code == 410, resp.text
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_removed_invited_member_loses_tenant_access(
    client: AsyncClient,
) -> None:
    """Removing an invited member invalidates tenant access despite legacy Membership."""
    owner_data = await _signup(client, "owner-removed@example.com", org_name="removed-firm")
    org_id = owner_data["organization"]["id"]

    invite_resp = await client.post(
        f"/api/v1/orgs/{org_id}/invites",
        json={"email": "removed-member@example.com", "role": "member"},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    raw_token = invite_resp.json()["invite_url"].split("/invite/")[-1]

    dataset_resp = await client.post("/api/v1/datasets", json={"name": "owner dataset"})
    assert dataset_resp.status_code == 201, dataset_resp.text
    pipeline_resp = await client.post(
        "/api/v1/pipelines",
        json={"name": "owner pipeline", "nodes": []},
    )
    assert pipeline_resp.status_code == 201, pipeline_resp.text
    pipeline_id = pipeline_resp.json()["id"]

    await client.post("/api/v1/auth/logout")
    member_data = await _signup(
        client,
        "removed-member@example.com",
        org_name="removed-member-personal",
    )
    member_user_id = member_data["user"]["id"]

    accept_resp = await client.post("/api/v1/invites/accept", json={"token": raw_token})
    assert accept_resp.status_code == 200, accept_resp.text
    stale_member_cookie = client.cookies[COOKIE_NAME]

    await client.post("/api/v1/auth/logout")
    await _login(client, "owner-removed@example.com")
    remove_resp = await client.delete(f"/api/v1/orgs/{org_id}/members/{member_user_id}")
    assert remove_resp.status_code == 204, remove_resp.text

    client.cookies.set(COOKIE_NAME, stale_member_cookie)

    checks = [
        ("GET", "/api/v1/datasets", None),
        ("POST", "/api/v1/datasets", {"name": "stale dataset"}),
        ("GET", "/api/v1/pipelines", None),
        ("POST", "/api/v1/pipelines", {"name": "stale pipeline", "nodes": []}),
        ("GET", "/api/v1/runs", None),
        ("POST", f"/api/v1/pipelines/{pipeline_id}/runs", {"query": "stale"}),
    ]
    for method, url, json_body in checks:
        resp = await client.request(method, url, json=json_body)
        assert resp.status_code == 401, f"{method} {url}: {resp.status_code} {resp.text}"
