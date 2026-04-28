"""Usage tracking service — record per-request events and aggregate daily."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import UsageEvent

logger = logging.getLogger(__name__)

# Imported lazily to avoid circular imports at module load time.
# Actual import happens inside record_usage_event.

# ---------------------------------------------------------------------------
# Pricing table (USD per 1 000 tokens)
# ---------------------------------------------------------------------------

#
# Client-facing prices (USD per 1 000 tokens) — already include:
#   - DeepSeek wholesale cost (cache-miss): input $0.14/1M, output $0.28/1M
#   - 6% VAT on the upstream payment
#   - 6% NPD tax on incoming revenue (effective gross-up 1/0.94 ≈ 1.064)
#   - margin to cover compute, storage, idle and ops
#
# Equivalent in RUB at $1 ≈ ₽95:  ₽20/1M input  /  ₽50/1M output  ≈  ₽30/1M for a 2:1 mix.
# When the wholesale list price changes, update wholesale_*_per_1m_usd below
# and re-derive the per-1K client number.
MODEL_PRICING_USD_PER_1K: dict[str, dict[str, float]] = {
    "deepseek/deepseek-v4-flash": {"prompt": 0.00021, "completion": 0.00053},
    "deepseek/deepseek-chat": {"prompt": 0.00021, "completion": 0.00053},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Calculate cost in USD for a given model and token counts."""
    pricing = MODEL_PRICING_USD_PER_1K.get(model, {"prompt": 0.0, "completion": 0.0})
    raw = (prompt_tokens * pricing["prompt"] + completion_tokens * pricing["completion"]) / 1000
    return Decimal(str(raw)).quantize(Decimal("0.000001"))


async def record_usage_event(
    db: AsyncSession,
    *,
    org_id: str,
    api_key_id: str | None,
    pipeline_id: str | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int | None = None,
) -> None:
    """Insert a UsageEvent row and atomically deduct from org balance.

    Fail-safe: logs warning on DB error, never raises.
    Balance deduction is always recorded even if it would bring balance negative
    (overspend on 1 request is acceptable for MVP; pre-flight guard is in rate_limiter).
    """
    from ragp_api.services.billing import deduct_balance

    try:
        cost = calculate_cost(model, prompt_tokens, completion_tokens)
        event = UsageEvent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            api_key_id=api_key_id,
            pipeline_id=pipeline_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
        db.add(event)
        await db.flush()  # get event.id without committing yet

        if cost > Decimal("0"):
            try:
                await deduct_balance(
                    db,
                    org_id=org_id,
                    amount=cost,
                    reference_type="usage_event",
                    reference_id=event.id,
                    allow_negative=True,  # record deduction even on overspend
                )
            except Exception:
                logger.warning(
                    "Balance deduction failed for org=%s cost=%s; usage event still recorded",
                    org_id,
                    cost,
                    exc_info=True,
                )

        await db.commit()
    except Exception:
        logger.warning("Failed to record usage event for org=%s", org_id, exc_info=True)
        await db.rollback()


def build_usage_summary(rows: Sequence[Any], days: int) -> dict[str, Any]:
    """Build the summary response from usage_daily rows.

    Each row must expose: day, model, total_prompt_tokens,
    total_completion_tokens, total_cost_usd, request_count.
    """
    from collections import defaultdict

    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        day_str = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
        by_day[day_str].append(
            {
                "model": row.model,
                "prompt_tokens": int(row.total_prompt_tokens),
                "completion_tokens": int(row.total_completion_tokens),
                "cost_usd": float(row.total_cost_usd),
                "request_count": int(row.request_count),
            }
        )

    days_list = []
    grand_total = Decimal("0")
    for day_str, models in sorted(by_day.items(), reverse=True):
        day_total = sum(Decimal(str(m["cost_usd"])) for m in models)
        grand_total += day_total
        days_list.append(
            {
                "day": day_str,
                "models": models,
                "total_cost_usd": float(day_total),
            }
        )

    return {
        "days": days_list,
        "total_cost_usd": float(grand_total),
        "period_days": days,
    }
