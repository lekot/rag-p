"""Org members and invites endpoints.

Known limitation: invite emails are NOT sent automatically (no SMTP in prod).
The invite URL is returned directly so the admin can copy and share it via
Telegram / Slack / etc.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgInvite, OrgMember, OrgRole, User
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.services.permissions import require_role

router = APIRouter(tags=["orgs"])

_BASE_URL = "https://lekottt.ru"
_INVITE_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MemberOut(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: str


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    created_at: str
    expires_at: str
    accepted_at: str | None


class InviteCreatedOut(BaseModel):
    id: str
    invite_url: str


class InviteIn(BaseModel):
    email: EmailStr
    role: str = "member"


class AcceptInviteIn(BaseModel):
    token: str


class PatchMemberIn(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_invite_role(role: str) -> None:
    if role not in (OrgRole.admin, OrgRole.member):
        raise HTTPException(
            status_code=422,
            detail="role must be 'admin' or 'member' (owner cannot be invited)",
        )


def _validate_org_role(role: str) -> None:
    if role not in (OrgRole.owner, OrgRole.admin, OrgRole.member):
        raise HTTPException(status_code=422, detail="Invalid role")


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@router.get("/api/v1/orgs/{org_id}/members", response_model=list[MemberOut])
async def list_members(
    org_id: str,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await require_role(db, current_user.id, org_id, OrgRole.member)

    rows = await db.execute(
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.created_at)
    )
    return [
        MemberOut(
            user_id=m.user_id,
            email=u.email,
            role=m.role,
            created_at=m.created_at.isoformat(),
        )
        for m, u in rows.all()
    ]


@router.delete("/api/v1/orgs/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: str,
    user_id: str,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_role(db, current_user.id, org_id, OrgRole.admin)

    target = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
        )
    )
    member = target.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Cannot remove the last owner
    if member.role == OrgRole.owner:
        owners_result = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.role == OrgRole.owner,
            )
        )
        if len(owners_result.scalars().all()) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")

    await db.delete(member)
    await db.commit()


@router.patch("/api/v1/orgs/{org_id}/members/{user_id}", response_model=MemberOut)
async def patch_member(
    org_id: str,
    user_id: str,
    body: PatchMemberIn,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _validate_org_role(body.role)
    await require_role(db, current_user.id, org_id, OrgRole.owner)

    target = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
        )
    )
    member = target.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Cannot demote self if last owner
    if user_id == current_user.id and member.role == OrgRole.owner and body.role != OrgRole.owner:
        owners_result = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.role == OrgRole.owner,
            )
        )
        if len(owners_result.scalars().all()) <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote yourself as the last owner")

    member.role = body.role

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    await db.refresh(member)
    return MemberOut(
        user_id=member.user_id,
        email=user.email,
        role=member.role,
        created_at=member.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


@router.post("/api/v1/orgs/{org_id}/invites", response_model=InviteCreatedOut, status_code=201)
async def create_invite(
    org_id: str,
    body: InviteIn,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _validate_invite_role(body.role)
    current_role = await require_role(db, current_user.id, org_id, OrgRole.admin)

    # Admin can only invite members, not other admins
    if current_role == OrgRole.admin and body.role == OrgRole.admin:
        raise HTTPException(status_code=403, detail="Admins can only invite members, not admins")

    raw_token = secrets.token_urlsafe(48)  # ~64 chars URL-safe
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)

    invite = OrgInvite(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email=str(body.email),
        role=body.role,
        token_hash=token_hash,
        invited_by=current_user.id,
        created_at=now,
        expires_at=now + timedelta(days=_INVITE_TTL_DAYS),
        accepted_at=None,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    invite_url = f"{_BASE_URL}/invite/{raw_token}"
    return InviteCreatedOut(id=invite.id, invite_url=invite_url)


@router.get("/api/v1/orgs/{org_id}/invites", response_model=list[InviteOut])
async def list_invites(
    org_id: str,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await require_role(db, current_user.id, org_id, OrgRole.admin)

    now = datetime.now(UTC)
    result = await db.execute(
        select(OrgInvite)
        .where(
            OrgInvite.org_id == org_id,
            OrgInvite.accepted_at.is_(None),
            OrgInvite.expires_at > now,
        )
        .order_by(OrgInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [
        InviteOut(
            id=i.id,
            email=i.email,
            role=i.role,
            created_at=i.created_at.isoformat(),
            expires_at=i.expires_at.isoformat(),
            accepted_at=i.accepted_at.isoformat() if i.accepted_at else None,
        )
        for i in invites
    ]


@router.delete("/api/v1/orgs/{org_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(
    org_id: str,
    invite_id: str,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_role(db, current_user.id, org_id, OrgRole.admin)

    result = await db.execute(
        select(OrgInvite).where(
            OrgInvite.id == invite_id,
            OrgInvite.org_id == org_id,
        )
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")

    await db.delete(invite)
    await db.commit()


@router.post("/api/v1/invites/accept", status_code=200)
async def accept_invite(
    body: AcceptInviteIn,
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = datetime.now(UTC)

    result = await db.execute(select(OrgInvite).where(OrgInvite.token_hash == token_hash))
    invite = result.scalar_one_or_none()

    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found or already used")

    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already accepted")

    # expires_at may be naive (SQLite) or aware (Postgres) — normalise before comparing
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise HTTPException(status_code=410, detail="Invite has expired")

    # Check if already a member
    existing = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == invite.org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Already a member of this organization")

    member = OrgMember(
        id=str(uuid.uuid4()),
        org_id=invite.org_id,
        user_id=current_user.id,
        role=invite.role,
    )
    db.add(member)

    invite.accepted_at = now
    await db.commit()

    return {"org_id": invite.org_id, "role": invite.role}
