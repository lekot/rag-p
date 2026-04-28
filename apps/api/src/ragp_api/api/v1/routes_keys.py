"""API key management endpoints."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Membership, User
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.services.audit import log_audit_event

router = APIRouter(prefix="/keys", tags=["keys"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KeyCreateIn(BaseModel):
    name: str


class KeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    last_used_at: datetime | None = None
    created_at: datetime


class KeyCreatedOut(BaseModel):
    id: str
    key: str  # Full key -- returned ONCE only
    name: str
    key_prefix: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_org_id(user: User, db: AsyncSession) -> str:
    """Return the first organization_id for the user."""
    result = await db.execute(
        select(Membership.organization_id).where(Membership.user_id == user.id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[KeyOut])
async def list_keys(
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    org_id = await _get_user_org_id(user, db)
    result = await db.execute(
        select(ApiKey).where(ApiKey.organization_id == org_id).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        KeyOut(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            last_used_at=k.last_used_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.post("", response_model=KeyCreatedOut, status_code=201)
async def create_key(
    body: KeyCreateIn,
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    org_id = await _get_user_org_id(user, db)

    # Generate: rgp_ + 32 random hex chars
    raw_secret = "rgp_" + os.urandom(16).hex()
    key_prefix = raw_secret[:8]
    key_hash = hashlib.sha256(raw_secret.encode()).hexdigest()

    api_key = ApiKey(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=user.id,
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    await db.flush()

    await log_audit_event(
        db,
        org_id=org_id,
        user_id=user.id,
        event_type="key.create",
        resource_type="key",
        resource_id=api_key.id,
        metadata={"prefix": key_prefix},
        request=request,
    )
    await db.commit()
    await db.refresh(api_key)

    return KeyCreatedOut(
        id=api_key.id,
        key=raw_secret,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
    )


@router.delete("/{key_id}", status_code=204)
async def delete_key(
    key_id: str,
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    org_id = await _get_user_org_id(user, db)
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(api_key)
    await log_audit_event(
        db,
        org_id=org_id,
        user_id=user.id,
        event_type="key.revoke",
        resource_type="key",
        resource_id=key_id,
        metadata={},
        request=request,
    )
    await db.commit()
