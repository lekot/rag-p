"""Usage tracking service — record per-request events and aggregate daily."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import UsageEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing table (USD per 1 000 tokens)
# ---------------------------------------------------------------------------

MODEL_PRICING_USD_PER_1K: dict[str, dict[str, float]] = {
    "deepseek/deepseek-v4-flash": {"prompt": 0.00027, "completion": 0.0011},
    "deepseek/deepseek-chat": {"prompt": 0.00027, "completion": 0.0011},
    "openai/gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "openai/gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "openai/gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
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
    """Insert a UsageEvent row.  Fail-safe: logs warning on DB error, never raises."""
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
        await db.commit()
    except Exception:
        logger.warning("Failed to record usage event for org=%s", org_id, exc_info=True)
        await db.rollback()


def build_usage_summary(rows: list[Any], days: int) -> dict[str, Any]:
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
