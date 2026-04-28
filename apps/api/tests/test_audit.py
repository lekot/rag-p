"""Tests for audit log: event creation and access control."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import AuditEvent, OrgMember

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str = "audit_user@example.com",
    password: str = "s3cr3t!",
    org_name: str | None = "audit-org",
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
    from sqlalchemy import insert

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
async def test_signup_creates_audit_event(client: AsyncClient, db_session: AsyncSession) -> None:
    """Signing up should produce a user.signup audit event."""
    data = await _signup(client, email="signup_audit@example.com", org_name="sorg")
    org_id = data["organization"]["id"]

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "user.signup",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "user.signup audit event not found"
    assert event.resource_type == "user"
    assert "email" in event.metadata_json


@pytest.mark.asyncio
async def test_login_creates_audit_event(client: AsyncClient, db_session: AsyncSession) -> None:
    """Login should produce a user.login audit event."""
    data = await _signup(client, email="login_audit@example.com", org_name="lorg")
    org_id = data["organization"]["id"]

    await client.post("/api/v1/auth/logout")
    await _login(client, email="login_audit@example.com")

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "user.login",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "user.login audit event not found"
    assert event.resource_type == "user"


@pytest.mark.asyncio
async def test_dataset_upload_creates_audit_event_with_filename(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Uploading a document should create a dataset.upload audit event with filename."""
    data = await _signup(client, email="upload_audit@example.com", org_name="uorg")
    org_id = data["organization"]["id"]

    # Create dataset first
    create_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": org_id},
        json={"name": "audit-ds", "organization_id": org_id},
    )
    assert create_resp.status_code == 201, create_resp.text
    dataset_id = create_resp.json()["id"]

    # Upload a small text file
    file_content = b"Hello audit world"
    upload_resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        files={"file": ("hello.txt", file_content, "text/plain")},
        headers={"X-Organization-Id": org_id},
    )
    assert upload_resp.status_code == 201, upload_resp.text

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "dataset.upload",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "dataset.upload audit event not found"
    assert event.metadata_json.get("filename") == "hello.txt"
    assert event.metadata_json.get("size") == len(file_content)


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_request(
    client: AsyncClient,
) -> None:
    """If audit log insert fails, the main endpoint should still return 200/201."""
    with patch(
        "ragp_api.services.audit.log_audit_event",
        new_callable=AsyncMock,
        side_effect=Exception("DB exploded"),
    ):
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "fail_audit@example.com",
                "password": "s3cr3t!",
                "organization_name": "failorg",
            },
        )
    # Signup should succeed even if audit log insertion raises
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_member_cannot_view_audit(client: AsyncClient, db_session: AsyncSession) -> None:
    """A plain member should get 403 when requesting audit events."""
    owner_data = await _signup(client, email="owner_audit@example.com", org_name="aorg")
    org_id = owner_data["organization"]["id"]

    member_data = await _signup(client, email="member_audit@example.com", org_name="morg")
    member_user_id = member_data["user"]["id"]
    await _seed_org_member(db_session, org_id, member_user_id, "member")

    await client.post("/api/v1/auth/logout")
    await _login(client, email="member_audit@example.com")

    resp = await client.get(f"/api/v1/orgs/{org_id}/audit")
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_admin_can_view_audit_filtered_by_event_type(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An admin should be able to view audit events filtered by event_type."""
    owner_data = await _signup(client, email="owner_audit2@example.com", org_name="aorg2")
    org_id = owner_data["organization"]["id"]

    admin_data = await _signup(client, email="admin_audit2@example.com", org_name="adorg2")
    admin_user_id = admin_data["user"]["id"]
    await _seed_org_member(db_session, org_id, admin_user_id, "admin")

    await client.post("/api/v1/auth/logout")
    await _login(client, email="admin_audit2@example.com")

    resp = await client.get(
        f"/api/v1/orgs/{org_id}/audit",
        params={"event_type": "user.signup"},
    )
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert isinstance(events, list)
    for e in events:
        assert e["event_type"] == "user.signup"
