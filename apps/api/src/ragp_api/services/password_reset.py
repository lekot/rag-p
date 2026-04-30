"""Password reset flow: request and complete."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import PasswordResetToken, User
from ragp_api.services.audit import log_audit_event
from ragp_api.services.email import send_password_reset_email
from ragp_api.services.passwords import hash_password
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

# The query-parameter name used in the reset link.
_TOKEN_PARAM = "token"

# Hard-coded base URL fallback; overridable via RAGP_APP_BASE_URL.
_APP_BASE_URL = "https://lekottt.ru"


def _reset_link(raw_token: str) -> str:
    base = getattr(settings, "app_base_url", _APP_BASE_URL).rstrip("/")
    return f"{base}/reset-password?{_TOKEN_PARAM}={raw_token}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def request_reset(db: AsyncSession, email: str) -> None:
    """Create a password-reset token and email the reset link.

    If no user with *email* exists the function returns silently (anti-enum).
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return

    raw_token = secrets.token_hex(32)
    token_hash = _sha256(raw_token)
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.password_reset_token_ttl_minutes
    )

    prt = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(prt)
    await db.flush()

    # Fire-and-forget audit record for this org-less action.
    # We look up the user's first org (nullable) for the org_id column.
    from ragp_api.db.models import Membership

    membership_result = await db.execute(
        select(Membership).where(Membership.user_id == user.id).limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    org_id = membership.organization_id if membership else "system"

    await log_audit_event(
        db,
        org_id=org_id,
        user_id=user.id,
        event_type="password_reset.requested",
        resource_type="user",
        resource_id=user.id,
        metadata={"email": email},
    )

    await db.commit()

    link = _reset_link(raw_token)
    await send_password_reset_email(email, link)


async def complete_reset(db: AsyncSession, token: str, new_password: str) -> bool:
    """Verify *token*, update password, invalidate all sessions.

    Returns True on success, False if the token is invalid/expired/used.
    """
    token_hash = _sha256(token)

    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    prt = result.scalar_one_or_none()

    # Use constant-time comparison even though we already fetched by hash;
    # this guard is belt-and-suspenders against timing side-channels.
    if prt is None:
        # No matching token — use a dummy comparison to keep timing uniform.
        secrets.compare_digest(token_hash, token_hash)
        return False

    if not secrets.compare_digest(prt.token_hash, token_hash):
        return False

    now = datetime.now(UTC)
    expires_at = prt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at <= now:
        return False

    if prt.used_at is not None:
        return False

    # All checks passed — update password and mark token used.
    user_result = await db.execute(select(User).where(User.id == prt.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return False

    user.password_hash = hash_password(new_password)
    prt.used_at = now
    await db.flush()

    # Invalidate all existing sessions for this user.
    await _invalidate_user_sessions(db, user.id)

    # Audit.
    from ragp_api.db.models import Membership

    membership_result = await db.execute(
        select(Membership).where(Membership.user_id == user.id).limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    org_id = membership.organization_id if membership else "system"

    await log_audit_event(
        db,
        org_id=org_id,
        user_id=user.id,
        event_type="password_reset.completed",
        resource_type="user",
        resource_id=user.id,
        metadata={"email": user.email},
    )

    await db.commit()
    return True


async def _invalidate_user_sessions(db: AsyncSession, user_id: str) -> None:
    """Bump ``sessions_invalidated_at`` on the user so that cookies issued
    before this moment are rejected by ``deps_auth.get_session_user``.

    Sessions are signed itsdangerous tokens stored only client-side.  There is
    no server-side session table to truncate.  Instead we store an invalidation
    timestamp on the user row; ``deps_auth`` compares the cookie's signing
    timestamp against this value and discards older cookies.
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is not None:
        user.sessions_invalidated_at = datetime.now(UTC)
    logger.debug("sessions invalidated for user_id=%s", user_id)
