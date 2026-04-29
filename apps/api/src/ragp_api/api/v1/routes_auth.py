"""Authentication endpoints: signup, login, logout, me."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Membership, Organization, OrgMember, User
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.deps_auth import COOKIE_NAME, _get_user_org, require_session_user
from ragp_api.services.audit import log_audit_event
from ragp_api.services.passwords import hash_password, verify_password
from ragp_api.services.rate_limiter import check_login_attempt
from ragp_api.services.sessions import make_session_cookie, read_session_cookie
from ragp_api.services.subscription import has_active_subscription
from ragp_api.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower())[:64]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SignupIn(BaseModel):
    email: EmailStr
    password: str
    organization_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class AuthOut(BaseModel):
    user: UserOut
    organization: OrgOut
    # Drives post-signup UX: when False the web app routes the user to
    # /pricing; when True the dashboard becomes the natural landing page.
    # Defaulted for backward compatibility with any callers that may still
    # construct AuthOut without the field.
    has_active_subscription: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Resolve the client IP for rate-limit keying.

    Honours ``X-Forwarded-For`` (first hop) when present so requests behind a
    trusted reverse proxy are not all bucketed together. Falls back to
    ``request.client.host`` and finally to ``"unknown"`` when neither is
    available.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _set_session_cookie(response: Response, user_id: str, org_id: str) -> None:
    token = make_session_cookie(user_id, org_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthOut, status_code=201)
async def signup(
    body: SignupIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create user
    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)

    # Create organization
    if body.organization_name:
        org_name = body.organization_name
        org_slug = _slugify(body.organization_name)
    else:
        local_part = body.email.split("@")[0]
        org_name = local_part
        org_slug = _slugify(local_part)

    # Ensure slug uniqueness
    base_slug = org_slug
    counter = 0
    while True:
        slug_result = await db.execute(select(Organization).where(Organization.slug == org_slug))
        if slug_result.scalar_one_or_none() is None:
            break
        counter += 1
        org_slug = f"{base_slug}-{counter}"

    org = Organization(
        id=str(uuid.uuid4()),
        name=org_name,
        slug=org_slug,
    )
    db.add(org)

    # Flush to get IDs before creating membership
    await db.flush()

    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role="owner",
    )
    db.add(membership)

    # Also add to org_members for new multi-user role system
    org_member = OrgMember(
        id=str(uuid.uuid4()),
        org_id=org.id,
        user_id=user.id,
        role="owner",
    )
    db.add(org_member)

    await log_audit_event(
        db,
        org_id=org.id,
        user_id=user.id,
        event_type="user.signup",
        resource_type="user",
        resource_id=user.id,
        metadata={"email": user.email, "org_name": org.name},
        request=request,
    )

    # No starting balance is granted on signup.
    # New organisations must purchase a plan via /pricing → ЮKassa
    # before making RAG queries.

    await db.commit()
    await db.refresh(user)
    await db.refresh(org)

    _set_session_cookie(response, user.id, org.id)

    # Brand-new orgs never have a subscription yet — this is the explicit
    # signal the web app uses to redirect to /pricing.
    return AuthOut(
        user=UserOut(id=user.id, email=user.email),
        organization=OrgOut(id=org.id, name=org.name, slug=org.slug, role="owner"),
        has_active_subscription=False,
    )


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
) -> Any:
    # Brute-force guard: sliding window per (IP, email). Counter is incremented
    # for every attempt — including successful ones — so a guessed password on
    # the N-th try still leaves the attacker locked out for the window.
    ip = _client_ip(request)
    ok, retry_after = await check_login_attempt(redis, ip, body.email, settings)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="too_many_login_attempts",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.deletion_requested_at is not None:
        raise HTTPException(status_code=403, detail="account_pending_deletion")

    # Get user's primary membership (prefer owner role)
    mem_result = await db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
        .limit(1)
    )
    row = mem_result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="User has no organization")
    membership, org = row

    _set_session_cookie(response, user.id, org.id)

    await log_audit_event(
        db,
        org_id=org.id,
        user_id=user.id,
        event_type="user.login",
        resource_type="user",
        resource_id=user.id,
        metadata={},
        request=request,
    )
    has_sub = await has_active_subscription(db, org.id)
    await db.commit()

    return AuthOut(
        user=UserOut(id=user.id, email=user.email),
        organization=OrgOut(id=org.id, name=org.name, slug=org.slug, role=membership.role),
        has_active_subscription=has_sub,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        parsed = read_session_cookie(token)
        if parsed:
            user_id, org_id = parsed
            await log_audit_event(
                db,
                org_id=org_id,
                user_id=user_id,
                event_type="user.logout",
                resource_type="user",
                resource_id=user_id,
                metadata={},
                request=request,
            )
            await db.commit()
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=AuthOut)
async def me(
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    preferred_org_id: str | None = None
    token = request.cookies.get(COOKIE_NAME)
    if token:
        parsed = read_session_cookie(token)
        if parsed and parsed[0] == user.id:
            preferred_org_id = parsed[1]

    result = await _get_user_org(user, db, preferred_org_id=preferred_org_id)
    if result is None:
        raise HTTPException(status_code=401, detail="No organization found")
    user_dict, org_dict = result
    has_sub = await has_active_subscription(db, org_dict["id"])
    return AuthOut(
        user=UserOut(**user_dict),
        organization=OrgOut(**org_dict),
        has_active_subscription=has_sub,
    )
