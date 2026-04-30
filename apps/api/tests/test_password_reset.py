"""Tests for the password-reset flow.

Coverage:
- request_reset with unknown email → 200, no token created
- request_reset with known email  → 200, token created, send_password_reset_email called
- complete_reset with valid token  → password changed, new login succeeds
- complete_reset with expired token → 400
- complete_reset twice (single-use) → second attempt returns 400
- sessions invalidated after successful reset (old cookie → 401 on /me)
- audit events recorded (password_reset.requested + .completed)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import AuditEvent, PasswordResetToken, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str = "user@example.com",
    password: str = "pass123",
) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": "TestOrg"},
    )
    assert resp.status_code == 201


async def _login(client: AsyncClient, email: str, password: str) -> int:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.status_code


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unknown email must still return 200 (anti-enumeration)."""
    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody@example.com"},
    )
    assert resp.status_code == 200

    # No token should have been created.
    result = await db_session.execute(select(PasswordResetToken))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_forgot_password_known_email_creates_token_and_sends_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Known email: token is persisted and send_password_reset_email is called."""
    email = "known@example.com"
    await _signup(client, email=email, password="secret!")

    sent_calls: list[tuple[str, str]] = []

    async def fake_send(to: str, link: str) -> None:
        sent_calls.append((to, link))

    with patch(
        "ragp_api.services.password_reset.send_password_reset_email",
        new=AsyncMock(side_effect=fake_send),
    ):
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email},
        )

    assert resp.status_code == 200

    result = await db_session.execute(
        select(PasswordResetToken).join(User, User.id == PasswordResetToken.user_id).where(
            User.email == email
        )
    )
    tokens = result.scalars().all()
    assert len(tokens) == 1
    assert tokens[0].used_at is None

    assert len(sent_calls) == 1
    assert sent_calls[0][0] == email
    assert "reset-password" in sent_calls[0][1]


@pytest.mark.asyncio
async def test_reset_password_valid_token_changes_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Valid token allows password change; subsequent login with new password succeeds."""
    email = "resetme@example.com"
    old_pw = "oldpassword"
    new_pw = "newpassword123"
    await _signup(client, email=email, password=old_pw)

    # Extract the user's id.
    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()

    # Create a valid token directly in the DB.
    raw_token = "a" * 64  # 64 hex chars = 32 bytes
    prt = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(prt)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": new_pw},
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "ok"

    # Old password login must fail.
    assert await _login(client, email, old_pw) == 401

    # New password login must succeed.
    assert await _login(client, email, new_pw) == 200


@pytest.mark.asyncio
async def test_reset_password_expired_token_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Expired token (expires_at < now) must be rejected."""
    email = "expired@example.com"
    await _signup(client, email=email, password="pass123")

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()

    raw_token = "b" * 64
    prt = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw_token),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),  # already expired
    )
    db_session.add(prt)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "newpass"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_or_expired_token"


@pytest.mark.asyncio
async def test_reset_password_single_use_second_attempt_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Token may only be used once; second attempt returns 400."""
    email = "singleuse@example.com"
    await _signup(client, email=email, password="pass123")

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()

    raw_token = "c" * 64
    prt = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(prt)
    await db_session.commit()

    r1 = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "firstnew"},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "secondnew"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_sessions_invalidated_after_reset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """After a successful reset, the pre-reset session cookie must not pass /me."""
    import asyncio

    email = "sessreset@example.com"
    password = "pass123"
    await _signup(client, email=email, password=password)

    # Confirm /me works before reset.
    me_before = await client.get("/api/v1/auth/me")
    assert me_before.status_code == 200

    # We need the cookie to have been issued BEFORE sessions_invalidated_at.
    # The test client preserves the signup cookie.  We wait a small moment so
    # the invalidation timestamp is strictly after the cookie issue time.
    await asyncio.sleep(0.1)

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()

    raw_token = "d" * 64
    prt = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(prt)
    await db_session.commit()

    reset_resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "newpass999"},
    )
    assert reset_resp.status_code == 200

    # The old session cookie should now be rejected.
    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_audit_events_recorded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """password_reset.requested and .completed audit events must be present."""
    email = "audit@example.com"
    await _signup(client, email=email, password="pass123")

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()

    # Trigger request_reset via the endpoint (patches email to avoid side-effects).
    with patch(
        "ragp_api.services.password_reset.send_password_reset_email",
        new=AsyncMock(),
    ):
        req_resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email},
        )
    assert req_resp.status_code == 200

    # The DB only stores the
    # hash, so we trigger it via the service directly with a fresh token.
    raw_token = "e" * 64
    prt2 = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=_sha256(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(prt2)
    await db_session.commit()

    reset_resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": "newpass"},
    )
    assert reset_resp.status_code == 200

    # Check audit events.
    audit_result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.user_id == user.id,
            AuditEvent.event_type.in_(["password_reset.requested", "password_reset.completed"]),
        )
    )
    events = {e.event_type for e in audit_result.scalars().all()}
    assert "password_reset.requested" in events
    assert "password_reset.completed" in events
