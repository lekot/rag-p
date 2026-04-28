"""Authentication endpoints: signup, login, logout, me."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Membership, Organization, OrgMember, User
from ragp_api.deps import get_db
from ragp_api.deps_auth import COOKIE_NAME, _get_user_org, require_session_user
from ragp_api.services.passwords import hash_password, verify_password
from ragp_api.services.sessions import make_session_cookie

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, user_id: str, org_id: str) -> None:
    token = make_session_cookie(user_id, org_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production behind HTTPS
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthOut, status_code=201)
async def signup(
    body: SignupIn,
    response: Response,
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
    await db.commit()
    await db.refresh(user)
    await db.refresh(org)

    _set_session_cookie(response, user.id, org.id)

    return AuthOut(
        user=UserOut(id=user.id, email=user.email),
        organization=OrgOut(id=org.id, name=org.name, slug=org.slug, role="owner"),
    )


@router.post("/login", response_model=AuthOut)
async def login(
    body: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

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

    return AuthOut(
        user=UserOut(id=user.id, email=user.email),
        organization=OrgOut(id=org.id, name=org.name, slug=org.slug, role=membership.role),
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=AuthOut)
async def me(
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await _get_user_org(user, db)
    if result is None:
        raise HTTPException(status_code=401, detail="No organization found")
    user_dict, org_dict = result
    return AuthOut(
        user=UserOut(**user_dict),
        organization=OrgOut(**org_dict),
    )
