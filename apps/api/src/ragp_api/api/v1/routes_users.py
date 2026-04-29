"""GDPR / 152-ФЗ user data endpoints.

Endpoints
---------
POST /api/v1/users/me/export
    Returns a JSON dump of all org-attached content (datasets meta, runs,
    billing transactions, api_keys metadata without secrets, audit events of
    last 90 days). MVP is synchronous; large orgs receive 413 with a hint to
    use the future async export. Allowed via session cookie or API key.

POST /api/v1/users/me/delete
    Soft-deletes the current user and every org where they are owner by
    setting ``deletion_requested_at``. Cron-driven hard-delete with a 30-day
    retention is intentionally NOT implemented in this commit. Requires
    session auth (cookies); API key auth is rejected so that an exfiltrated
    key cannot nuke the account.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Organization, OrgMember, User
from ragp_api.deps import get_db
from ragp_api.deps_auth import COOKIE_NAME, require_session_user
from ragp_api.services.audit import log_audit_event
from ragp_api.services.sessions import read_session_cookie
from ragp_api.services.user_data import (
    MAX_EXPORT_BYTES,
    estimate_payload_size,
    export_org_data,
    request_account_deletion,
)

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExportUserOut(BaseModel):
    id: str
    email: str
    created_at: str | None
    deletion_requested_at: str | None


class ExportOrgOut(BaseModel):
    id: str
    name: str
    slug: str
    created_at: str | None
    deletion_requested_at: str | None


class ExportDatasetOut(BaseModel):
    id: str
    name: str
    source: str
    created_at: str | None


class ExportRunOut(BaseModel):
    id: str
    pipeline_version_id: str
    dataset_id: str | None
    status: str
    query: str | None
    metrics_json: dict[str, Any] | None
    started_at: str | None
    finished_at: str | None
    created_at: str | None


class ExportTransactionOut(BaseModel):
    id: str
    type: str
    amount_usd: str | None
    balance_after_usd: str | None
    reference_type: str | None
    reference_id: str | None
    note: str | None
    created_at: str | None


class ExportApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    last_used_at: str | None
    created_at: str | None


class ExportAuditEventOut(BaseModel):
    id: str
    event_type: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, Any]
    created_at: str | None


class ExportOut(BaseModel):
    exported_at: str
    user: ExportUserOut
    organization: ExportOrgOut
    datasets: list[ExportDatasetOut]
    runs: list[ExportRunOut]
    transactions: list[ExportTransactionOut]
    api_keys: list[ExportApiKeyOut]
    audit_events_recent_90d: list[ExportAuditEventOut]


class DeleteAccountOut(BaseModel):
    status: str
    purge_after: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_session_org(
    request: Request,
    db: AsyncSession,
    user: User,
) -> Organization:
    """Pick the organisation tied to the current session cookie.

    Falls back to the user's first owner-org membership. Raises 400 if the
    user has no org. Note: the dependency-injected ``user`` already passes the
    deletion-pending check inside ``require_session_user``.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        parsed = read_session_cookie(token)
        if parsed and parsed[0] == user.id:
            org_id = parsed[1]
            org_result = await db.execute(select(Organization).where(Organization.id == org_id))
            org = org_result.scalar_one_or_none()
            if org is not None:
                return org

    member_result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == user.id)
        .limit(1)
    )
    org = member_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=400, detail="user has no organization")
    return org


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/me/export", response_model=ExportOut)
async def export_my_data(
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Synchronously dump all data attached to the user's current organisation."""
    org = await _resolve_session_org(request, db, user)
    payload = await export_org_data(db, user=user, org=org)

    if estimate_payload_size(payload) > MAX_EXPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "export_too_large",
                "message": (
                    "Synchronous export exceeds the 100MB limit. "
                    "Use the async export endpoint (coming soon)."
                ),
            },
        )

    await log_audit_event(
        db,
        org_id=org.id,
        user_id=user.id,
        event_type="user.export",
        resource_type="user",
        resource_id=user.id,
        metadata={
            "datasets": len(payload["datasets"]),
            "runs": len(payload["runs"]),
            "transactions": len(payload["transactions"]),
            "api_keys": len(payload["api_keys"]),
            "audit_events": len(payload["audit_events_recent_90d"]),
        },
        request=request,
    )
    await db.commit()
    return payload


@router.post("/me/delete", response_model=DeleteAccountOut)
async def delete_my_account(
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Soft-delete the current user and every org where they are owner.

    API key auth is forbidden — the require_session_user dependency only
    accepts the session cookie, so a leaked key cannot trigger account
    deletion. Caller must additionally hold ``owner`` role in at least one
    organisation; admin/member roles can leave the org but not delete it.
    """
    owner_check = await db.execute(
        select(OrgMember.id).where(
            OrgMember.user_id == user.id,
            OrgMember.role == "owner",
        )
    )
    if owner_check.first() is None:
        raise HTTPException(status_code=403, detail="owner role required")

    deletion_at, purge_after = await request_account_deletion(db, user=user)

    org = await _resolve_session_org(request, db, user)
    await log_audit_event(
        db,
        org_id=org.id,
        user_id=user.id,
        event_type="user.delete_request",
        resource_type="user",
        resource_id=user.id,
        metadata={
            "deletion_requested_at": deletion_at.isoformat(),
            "purge_after": purge_after.isoformat(),
        },
        request=request,
    )
    await db.commit()

    return DeleteAccountOut(status="pending_deletion", purge_after=purge_after.isoformat())
