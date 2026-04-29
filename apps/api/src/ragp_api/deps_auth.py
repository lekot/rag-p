"""FastAPI dependencies for authentication and authorization.

Priority order for require_organization:
  1. Session cookie (ragp_session)
  2. Authorization: Bearer <api-key>
  3. X-Organization-Id header (legacy fallback, disabled unless explicitly configured)
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Membership, Organization, OrgMember, User
from ragp_api.deps import get_db
from ragp_api.services.sessions import COOKIE_NAME as _COOKIE_NAME
from ragp_api.services.sessions import read_session_cookie
from ragp_api.settings import settings

# Re-export for convenience (used by routes_auth)
COOKIE_NAME = _COOKIE_NAME

__all__ = [
    "COOKIE_NAME",
    "get_api_key_org",
    "get_session_user",
    "require_organization",
    "require_scope",
    "require_session_user",
    "_get_user_org",
]


# Scope hierarchy: admin > write > read.
_SCOPE_RANK: dict[str, int] = {"read": 1, "write": 2, "admin": 3}


def _scope_satisfies(have: str, need: str) -> bool:
    """Return True if `have` is at least as privileged as `need`."""
    return _SCOPE_RANK.get(have, 0) >= _SCOPE_RANK.get(need, 0)


def _is_key_expired(api_key: ApiKey) -> bool:
    """Return True if the api key has reached its expiration moment."""
    expires_at = api_key.expires_at
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


async def get_session_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Read session cookie and return the User, or None if absent/invalid.

    Users with ``deletion_requested_at`` set are treated as locked: this
    function raises ``HTTPException(403, account_pending_deletion)`` so the
    response is consistent across all auth-protected endpoints.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    parsed = read_session_cookie(token)
    if not parsed:
        return None
    user_id, _org_id = parsed
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is not None and user.deletion_requested_at is not None:
        raise HTTPException(status_code=403, detail="account_pending_deletion")
    return user


async def get_api_key_org(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[Organization, ApiKey] | None:
    """Read Authorization: Bearer header, validate API key, update last_used_at.

    Returns (Organization, ApiKey) or None when no/invalid bearer was supplied.

    Raises 401 with detail=key_expired/key_revoked if the key matches but is
    no longer usable, so callers cannot silently fall back to anonymous access.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    raw_key = auth_header.removeprefix("Bearer ").strip()
    if not raw_key:
        return None

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = key_result.scalar_one_or_none()
    if api_key is None:
        return None

    if api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="key_revoked")
    if _is_key_expired(api_key):
        raise HTTPException(status_code=401, detail="key_expired")

    # Update last_used_at
    api_key.last_used_at = datetime.now(UTC)
    await db.commit()

    org_result = await db.execute(
        select(Organization).where(Organization.id == api_key.organization_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        return None

    # Stash for downstream require_scope dependency
    request.state.api_key = api_key

    return org, api_key


async def require_organization(
    request: Request,
    db: AsyncSession = Depends(get_db),
    # Legacy fallback header — TODO: remove after UI migration
    x_organization_id: str | None = Header(default=None),
) -> Organization:
    """Resolve the current Organization from session, API key, or legacy header.

    Raises 401 if none of the auth mechanisms are present/valid.
    """
    # 1. Session cookie
    token = request.cookies.get(COOKIE_NAME)
    if token:
        parsed = read_session_cookie(token)
        if parsed:
            user_id, org_id = parsed
            # Block sessions tied to a user awaiting deletion.
            session_user_result = await db.execute(select(User).where(User.id == user_id))
            session_user = session_user_result.scalar_one_or_none()
            if session_user is not None and session_user.deletion_requested_at is not None:
                raise HTTPException(status_code=403, detail="account_pending_deletion")
            session_org_result = await db.execute(
                select(Organization).where(Organization.id == org_id)
            )
            session_org = session_org_result.scalar_one_or_none()
            if session_org is not None and session_org.deletion_requested_at is not None:
                raise HTTPException(status_code=403, detail="account_pending_deletion")
            if session_org and await _user_has_org_access(db, user_id, org_id):
                return session_org

    # 2. API key Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_key = auth_header.removeprefix("Bearer ").strip()
        bearer_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        bearer_key_result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == bearer_key_hash)
        )
        bearer_api_key = bearer_key_result.scalar_one_or_none()
        if bearer_api_key is not None:
            if bearer_api_key.revoked_at is not None:
                raise HTTPException(status_code=401, detail="key_revoked")
            if _is_key_expired(bearer_api_key):
                raise HTTPException(status_code=401, detail="key_expired")
            bearer_api_key.last_used_at = datetime.now(UTC)
            await db.commit()
            bearer_org_result = await db.execute(
                select(Organization).where(Organization.id == bearer_api_key.organization_id)
            )
            bearer_org = bearer_org_result.scalar_one_or_none()
            if bearer_org is not None and bearer_org.deletion_requested_at is not None:
                raise HTTPException(status_code=403, detail="account_pending_deletion")
            if bearer_org:
                # Stash for downstream require_scope dependency
                request.state.api_key = bearer_api_key
                return bearer_org

    # 3. Legacy X-Organization-Id header fallback. Disabled in production:
    # client-supplied tenant ids are not an auth boundary.
    if x_organization_id and settings.allow_legacy_org_header:
        legacy_result = await db.execute(
            select(Organization).where(Organization.id == x_organization_id)
        )
        legacy_org = legacy_result.scalar_one_or_none()
        if legacy_org:
            return legacy_org
        # If header is present but org not in DB, still return a stub org for
        # backward-compat with hardcoded staging org ID
        stub = Organization()
        stub.id = x_organization_id
        stub.name = "legacy"
        stub.slug = "legacy"
        return stub

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_session_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid session cookie. Raises 401 if absent or invalid."""
    user = await get_session_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_scope(min_scope: str) -> Callable[..., Any]:
    """Dependency factory enforcing API-key scope hierarchy (admin > write > read).

    Session-cookie callers (UI users) bypass this check — UI always has full
    permissions and is governed by org membership/role instead.

    Behaviour:
      - If the request carries a session cookie that resolves to a real user,
        the scope check is skipped.
      - If a Bearer API key is supplied, look it up and require the key's
        `scope` to satisfy `min_scope`; otherwise 403 ``insufficient_scope``.
      - If neither is present, the request remains anonymous from this
        dependency's perspective; it is up to other deps in the route
        signature (e.g. `require_organization`) to issue 401.
    """
    if min_scope not in _SCOPE_RANK:
        raise ValueError(f"Unknown scope: {min_scope!r}")

    async def _checker(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Cached api_key on request.state (populated by get_api_key_org /
        # require_organization) — fast path.
        api_key: ApiKey | None = getattr(request.state, "api_key", None)

        if api_key is None:
            # If a session cookie is attached, skip scope check (UI users).
            cookie = request.cookies.get(COOKIE_NAME)
            if cookie:
                parsed = read_session_cookie(cookie)
                if parsed:
                    return

            # Look up the bearer key directly so endpoints that don't
            # otherwise depend on get_api_key_org still get scope enforcement.
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                raw = auth_header.removeprefix("Bearer ").strip()
                if raw:
                    key_hash = hashlib.sha256(raw.encode()).hexdigest()
                    res = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
                    api_key = res.scalar_one_or_none()
                    if api_key is not None:
                        if api_key.revoked_at is not None:
                            raise HTTPException(status_code=401, detail="key_revoked")
                        if _is_key_expired(api_key):
                            raise HTTPException(status_code=401, detail="key_expired")
                        request.state.api_key = api_key

        if api_key is None:
            # No auth context — leave 401 to other deps (or allow public).
            return

        if not _scope_satisfies(api_key.scope, min_scope):
            raise HTTPException(
                status_code=403,
                detail={
                    "detail": "insufficient_scope",
                    "required": min_scope,
                    "have": api_key.scope,
                },
            )

    return _checker


async def _get_user_org(
    user: User,
    db: AsyncSession,
    preferred_org_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return user+org dicts, preferring the org selected in the session cookie."""
    if preferred_org_id is not None:
        org_member_result = await db.execute(
            select(OrgMember, Organization)
            .join(Organization, Organization.id == OrgMember.org_id)
            .where(OrgMember.user_id == user.id, OrgMember.org_id == preferred_org_id)
            .limit(1)
        )
        org_member_row = org_member_result.first()
        if org_member_row is not None:
            org_member, org = org_member_row
            return (
                {"id": user.id, "email": user.email},
                {"id": org.id, "name": org.name, "slug": org.slug, "role": org_member.role},
            )

        membership_result = await db.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(
                Membership.user_id == user.id,
                Membership.organization_id == preferred_org_id,
            )
            .limit(1)
        )
        membership_row = membership_result.first()
        if membership_row is not None:
            membership, org = membership_row
            return (
                {"id": user.id, "email": user.email},
                {"id": org.id, "name": org.name, "slug": org.slug, "role": membership.role},
            )

    uo_result = await db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.role)
        .limit(1)
    )
    row = uo_result.first()
    if row is None:
        return None
    membership, org = row
    return (
        {"id": user.id, "email": user.email},
        {"id": org.id, "name": org.name, "slug": org.slug, "role": membership.role},
    )


async def _user_has_org_access(db: AsyncSession, user_id: str, org_id: str) -> bool:
    membership_result = await db.execute(
        select(Membership.organization_id).where(
            Membership.user_id == user_id,
            Membership.organization_id == org_id,
        )
    )
    if membership_result.scalar_one_or_none() is not None:
        return True

    org_member_result = await db.execute(
        select(OrgMember.id).where(
            OrgMember.user_id == user_id,
            OrgMember.org_id == org_id,
        )
    )
    return org_member_result.scalar_one_or_none() is not None
