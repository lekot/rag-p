"""Sliding-window rate limiter backed by Redis.

Algorithm: sliding window log.
  - ZADD key timestamp timestamp
  - ZREMRANGEBYSCORE key 0 (now - window)
  - ZCARD key  → current request count in window
  - EXPIRE key window  (TTL cleanup)

Two counters per RAG query:
  - per API key:  rl:key:<api_key_id>
  - per org:      rl:org:<org_id>

Fail-open policy: if Redis is unavailable, the request is allowed through
and a WARNING is logged. Platform availability beats rate-limit enforcement.
"""

from __future__ import annotations

import logging
import math
import time
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.settings import Settings

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60


async def check(
    redis: Any,
    key: str,
    limit: int,
    window_seconds: int = _WINDOW_SECONDS,
) -> tuple[bool, int]:
    """Slide the window and check whether *key* is within *limit*.

    Returns:
        (True, 0)            — request is allowed.
        (False, retry_after) — request is blocked; retry_after is the number
                               of seconds until the oldest entry in the window
                               expires and a slot frees up.
    """
    now_ms = time.time()
    window_start = now_ms - window_seconds

    # Use a pipeline for atomicity and round-trip efficiency.
    pipe = redis.pipeline()
    pipe.zadd(key, {str(now_ms): now_ms})
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.zrange(key, 0, 0, withscores=True)  # oldest member
    pipe.expire(key, window_seconds + 1)
    results: list[Any] = await pipe.execute()

    count: int = results[2]
    oldest_members: list[tuple[bytes, float]] = results[3]

    if count <= limit:
        return True, 0

    # Calculate retry_after from the oldest entry in the window.
    if oldest_members:
        oldest_score: float = oldest_members[0][1]
        retry_after = math.ceil(oldest_score + window_seconds - now_ms)
        retry_after = max(retry_after, 1)
    else:
        retry_after = window_seconds

    return False, retry_after


async def check_rag_query_limits(
    redis: Any,
    org_id: str,
    api_key_id: str,
    settings: Settings,
    db: AsyncSession | None = None,
) -> None:
    """Check balance, per-key and per-org rate limits.

    Raises HTTPException(402) if balance is zero or negative.
    Raises HTTPException(429) if either rate limit is exceeded.
    Fails open if Redis raises any connection error.
    db is optional for backward-compat; balance check is skipped if None.
    """
    # --- Balance pre-flight check ---
    if db is not None:
        from ragp_api.services.billing import get_balance

        try:
            balance = await get_balance(db, org_id)
            if balance <= Decimal("0"):
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "insufficient_balance",
                        "balance_usd": float(balance),
                        "message": "Top up your balance at /account/billing",
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(
                "Balance check failed for org=%s (%s: %s) — failing open",
                org_id,
                type(exc).__name__,
                exc,
            )

    # --- Rate limiting ---
    try:
        key_redis_key = f"rl:key:{api_key_id}"
        ok_key, retry_key = await check(
            redis,
            key_redis_key,
            settings.rate_limit_per_key_rpm,
            _WINDOW_SECONDS,
        )
        if not ok_key:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_key)},
                detail={
                    "detail": "rate_limit_exceeded",
                    "scope": "key",
                    "limit": settings.rate_limit_per_key_rpm,
                    "window_seconds": _WINDOW_SECONDS,
                },
            )

        org_redis_key = f"rl:org:{org_id}"
        ok_org, retry_org = await check(
            redis,
            org_redis_key,
            settings.rate_limit_per_org_rpm,
            _WINDOW_SECONDS,
        )
        if not ok_org:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_org)},
                detail={
                    "detail": "rate_limit_exceeded",
                    "scope": "org",
                    "limit": settings.rate_limit_per_org_rpm,
                    "window_seconds": _WINDOW_SECONDS,
                },
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "Rate limiter: Redis unavailable (%s: %s) — failing open",
            type(exc).__name__,
            exc,
        )
