"""GDPR / 152-ФЗ data export and account deletion service.

Provides:
  - export_org_data: collect all org-attached content for a user (datasets meta,
    runs, billing transactions, api_keys metadata without secrets, audit
    events of last 90 days). Returns a JSON-serialisable dict.
  - request_account_deletion: soft-delete by setting deletion_requested_at on
    user and all their owner-org organisations. Cascade hard-delete is performed
    by a future cron after 30-day retention.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    ApiKey,
    AuditEvent,
    BillingTransaction,
    Dataset,
    Organization,
    OrgMember,
    Run,
    User,
)

# Retention before cron picks up the row for hard-delete.
RETENTION_DAYS = 30

# Hard cap on /export response size to protect API workers.
MAX_EXPORT_BYTES = 100 * 1024 * 1024  # 100 MB


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


async def export_org_data(
    db: AsyncSession,
    *,
    user: User,
    org: Organization,
) -> dict[str, Any]:
    """Build the full GDPR export payload for one user + one organisation.

    The returned dict is JSON-serialisable and contains only data the user is
    entitled to see (no other-org data, no plaintext secrets).
    """
    datasets_rows = (
        (await db.execute(select(Dataset).where(Dataset.organization_id == org.id))).scalars().all()
    )

    runs_rows = (await db.execute(select(Run).where(Run.organization_id == org.id))).scalars().all()

    tx_rows = (
        (await db.execute(select(BillingTransaction).where(BillingTransaction.org_id == org.id)))
        .scalars()
        .all()
    )

    api_keys_rows = (
        (await db.execute(select(ApiKey).where(ApiKey.organization_id == org.id))).scalars().all()
    )

    cutoff = datetime.now(UTC) - timedelta(days=90)
    audit_rows = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.org_id == org.id)
                .where(AuditEvent.created_at >= cutoff)
                .order_by(AuditEvent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": _iso(user.created_at),
            "deletion_requested_at": _iso(user.deletion_requested_at),
        },
        "organization": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "created_at": _iso(org.created_at),
            "deletion_requested_at": _iso(org.deletion_requested_at),
        },
        "datasets": [
            {
                "id": d.id,
                "name": d.name,
                "source": d.source,
                "created_at": _iso(d.created_at),
            }
            for d in datasets_rows
        ],
        "runs": [
            {
                "id": r.id,
                "pipeline_version_id": r.pipeline_version_id,
                "dataset_id": r.dataset_id,
                "status": r.status,
                "query": r.query,
                "metrics_json": r.metrics_json,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "created_at": _iso(r.created_at),
            }
            for r in runs_rows
        ],
        "transactions": [
            {
                "id": t.id,
                "type": t.type,
                "amount_usd": _decimal_to_str(t.amount_usd),
                "balance_after_usd": _decimal_to_str(t.balance_after_usd),
                "reference_type": t.reference_type,
                "reference_id": t.reference_id,
                "note": t.note,
                "created_at": _iso(t.created_at),
            }
            for t in tx_rows
        ],
        "api_keys": [
            # Secret material (key_hash, full key) is intentionally excluded.
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "last_used_at": _iso(k.last_used_at),
                "created_at": _iso(k.created_at),
            }
            for k in api_keys_rows
        ],
        "audit_events_recent_90d": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "ip_address": e.ip_address,
                "user_agent": e.user_agent,
                "metadata": e.metadata_json,
                "created_at": _iso(e.created_at),
            }
            for e in audit_rows
        ],
    }


def estimate_payload_size(payload: dict[str, Any]) -> int:
    """Conservative size estimate (bytes) for an export payload."""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


async def request_account_deletion(
    db: AsyncSession,
    *,
    user: User,
) -> tuple[datetime, datetime]:
    """Mark the user and every org where they are owner as pending deletion.

    Returns (deletion_requested_at, purge_after).
    """
    now = datetime.now(UTC)

    if user.deletion_requested_at is None:
        user.deletion_requested_at = now

    owner_org_ids = (
        (
            await db.execute(
                select(OrgMember.org_id).where(
                    OrgMember.user_id == user.id,
                    OrgMember.role == "owner",
                )
            )
        )
        .scalars()
        .all()
    )

    if owner_org_ids:
        orgs = (
            (await db.execute(select(Organization).where(Organization.id.in_(owner_org_ids))))
            .scalars()
            .all()
        )
        for org in orgs:
            if org.deletion_requested_at is None:
                org.deletion_requested_at = now

    await db.flush()

    purge_after = now + timedelta(days=RETENTION_DAYS)
    return now, purge_after
