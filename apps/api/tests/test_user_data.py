"""Tests for the GDPR / 152-ФЗ data-export and account-deletion endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    ApiKey,
    AuditEvent,
    BillingTransaction,
    Dataset,
    Organization,
    OrgMember,
    User,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str = "gdpr@example.com",
    password: str = "s3cr3t!",
    org_name: str = "gdpr-org",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": org_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_org_member(
    db_session: AsyncSession,
    org_id: str,
    user_id: str,
    role: str,
) -> None:
    db_session.add(
        OrgMember(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            role=role,
        )
    )
    await db_session.commit()


async def _seed_dataset(db_session: AsyncSession, org_id: str, name: str) -> str:
    ds_id = str(uuid.uuid4())
    db_session.add(Dataset(id=ds_id, organization_id=org_id, name=name))
    await db_session.commit()
    return ds_id


async def _seed_billing_tx(db_session: AsyncSession, org_id: str) -> str:
    tx_id = str(uuid.uuid4())
    db_session.add(
        BillingTransaction(
            id=tx_id,
            org_id=org_id,
            type="topup",
            amount_usd=Decimal("10.00"),
            balance_after_usd=Decimal("10.00"),
            reference_type="manual_topup",
        )
    )
    await db_session.commit()
    return tx_id


async def _seed_api_key(db_session: AsyncSession, org_id: str, user_id: str) -> str:
    key_id = str(uuid.uuid4())
    db_session.add(
        ApiKey(
            id=key_id,
            organization_id=org_id,
            user_id=user_id,
            name="ci",
            key_prefix="rgp_test",
            key_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    await db_session.commit()
    return key_id


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_returns_org_data_for_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data = await _signup(client, email="exp1@example.com", org_name="exp1")
    org_id = data["organization"]["id"]
    user_id = data["user"]["id"]

    await _seed_dataset(db_session, org_id, "ds-export")
    await _seed_billing_tx(db_session, org_id)
    await _seed_api_key(db_session, org_id, user_id)

    resp = await client.post("/api/v1/users/me/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "exp1@example.com"
    assert body["organization"]["id"] == org_id
    assert any(d["name"] == "ds-export" for d in body["datasets"])
    assert len(body["transactions"]) >= 1
    assert len(body["api_keys"]) >= 1


@pytest.mark.asyncio
async def test_export_excludes_other_org_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data_a = await _signup(client, email="exp_a@example.com", org_name="exp-a")
    org_a = data_a["organization"]["id"]

    # Independent organisation B with its own dataset; user A is NOT a member.
    org_b = Organization(id=str(uuid.uuid4()), name="other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(org_b)
    await db_session.commit()
    await _seed_dataset(db_session, org_b.id, "ds-secret-of-b")
    await _seed_dataset(db_session, org_a, "ds-of-a")

    resp = await client.post("/api/v1/users/me/export")
    assert resp.status_code == 200, resp.text
    names = [d["name"] for d in resp.json()["datasets"]]
    assert "ds-of-a" in names
    assert "ds-secret-of-b" not in names


@pytest.mark.asyncio
async def test_export_redacts_secret_fields(client: AsyncClient, db_session: AsyncSession) -> None:
    data = await _signup(client, email="exp_sec@example.com", org_name="exp-sec")
    org_id = data["organization"]["id"]
    user_id = data["user"]["id"]
    await _seed_api_key(db_session, org_id, user_id)

    resp = await client.post("/api/v1/users/me/export")
    assert resp.status_code == 200
    keys = resp.json()["api_keys"]
    assert len(keys) >= 1
    for k in keys:
        assert "key_hash" not in k
        assert "key" not in k
        assert k["key_prefix"]


# ---------------------------------------------------------------------------
# Delete-request tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_request_marks_user_and_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data = await _signup(client, email="del1@example.com", org_name="del1")
    org_id = data["organization"]["id"]
    user_id = data["user"]["id"]

    resp = await client.post("/api/v1/users/me/delete")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending_deletion"
    assert body["purge_after"]

    user_row = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()
    org_row = (
        await db_session.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one()
    assert user_row.deletion_requested_at is not None
    assert org_row.deletion_requested_at is not None


@pytest.mark.asyncio
async def test_delete_request_audit_logged(client: AsyncClient, db_session: AsyncSession) -> None:
    data = await _signup(client, email="del2@example.com", org_name="del2")
    org_id = data["organization"]["id"]

    resp = await client.post("/api/v1/users/me/delete")
    assert resp.status_code == 200

    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.org_id == org_id,
                AuditEvent.event_type == "user.delete_request",
            )
        )
    ).scalar_one_or_none()
    assert event is not None


@pytest.mark.asyncio
async def test_export_is_audit_logged(client: AsyncClient, db_session: AsyncSession) -> None:
    data = await _signup(client, email="exp_audit@example.com", org_name="exp-audit")
    org_id = data["organization"]["id"]

    resp = await client.post("/api/v1/users/me/export")
    assert resp.status_code == 200

    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.org_id == org_id,
                AuditEvent.event_type == "user.export",
            )
        )
    ).scalar_one_or_none()
    assert event is not None


@pytest.mark.asyncio
async def test_blocked_login_after_delete_request(client: AsyncClient) -> None:
    await _signup(client, email="blocked@example.com", password="pw!", org_name="blk")
    del_resp = await client.post("/api/v1/users/me/delete")
    assert del_resp.status_code == 200

    # Drop the session so we attempt a fresh login.
    await client.post("/api/v1/auth/logout")

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "blocked@example.com", "password": "pw!"},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["detail"] == "account_pending_deletion"


@pytest.mark.asyncio
async def test_delete_requires_owner_role(client: AsyncClient, db_session: AsyncSession) -> None:
    """A plain admin in an org should not be able to delete that org."""
    owner_data = await _signup(client, email="owner@example.com", org_name="ownerorg")
    org_id = owner_data["organization"]["id"]

    # Drop owner session, sign up a second user, then attach them to org_id as
    # an admin (not owner).
    await client.post("/api/v1/auth/logout")
    admin_data = await _signup(client, email="adm@example.com", org_name="admorg-stub")
    admin_user_id = admin_data["user"]["id"]

    # Wipe the admin's own owner-org membership so the only membership left is
    # the admin role injected on org_id below.
    await db_session.execute(OrgMember.__table__.delete().where(OrgMember.user_id == admin_user_id))
    await db_session.commit()
    await _seed_org_member(db_session, org_id, admin_user_id, "admin")

    # Re-login to make sure the cookie points at org_id.
    await client.post("/api/v1/auth/logout")
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "adm@example.com", "password": "s3cr3t!"},
    )
    assert login_resp.status_code == 200

    resp = await client.post("/api/v1/users/me/delete")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_via_api_key_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """API key auth must not satisfy the require_session_user dependency."""
    await _signup(client, email="apik@example.com", org_name="apik-org")
    create_resp = await client.post("/api/v1/keys", json={"name": "ci"})
    assert create_resp.status_code == 201
    api_key = create_resp.json()["key"]

    # Drop the cookie and call /delete with the bearer key only.
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/users/me/delete",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 401
