"""Usage & billing endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgRole, UsageDaily, UsageEvent, User
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.services.permissions import require_role
from ragp_api.services.usage import build_usage_summary

router = APIRouter(tags=["usage"])


@router.get("/api/v1/orgs/{org_id}/usage/summary")
async def get_usage_summary(
    org_id: str,
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Usage summary by day and model (requires member+)."""
    await require_role(db, current_user.id, org_id, OrgRole.member)

    # SQLite-compatible: cast day to text for comparison
    # For Postgres the date arithmetic works natively; for SQLite we use a workaround
    result = await db.execute(
        select(UsageDaily)
        .where(
            UsageDaily.org_id == org_id,
            UsageDaily.day >= func.date(func.now(), f"-{days} days"),
        )
        .order_by(UsageDaily.day.desc(), UsageDaily.model)
    )
    rows = result.scalars().all()
    return build_usage_summary(rows, days)


@router.get("/api/v1/orgs/{org_id}/usage/events")
async def get_usage_events(
    org_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Raw usage events (requires admin+)."""
    await require_role(db, current_user.id, org_id, OrgRole.admin)

    result = await db.execute(
        select(UsageEvent)
        .where(UsageEvent.org_id == org_id)
        .order_by(UsageEvent.ts.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "ts": e.ts.isoformat(),
            "model": e.model,
            "prompt_tokens": e.prompt_tokens,
            "completion_tokens": e.completion_tokens,
            "cost_usd": float(e.cost_usd),
            "latency_ms": e.latency_ms,
            "api_key_id": e.api_key_id,
            "pipeline_id": e.pipeline_id,
        }
        for e in events
    ]
