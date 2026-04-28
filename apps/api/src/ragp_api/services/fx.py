"""Foreign exchange rate service.

Fetches USD->RUB rate from the Central Bank of Russia (CBR) API and caches it
in Redis for 24 hours to avoid hammering the external endpoint on every request.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE_KEY = "fx:usd_rub"
_CACHE_TTL_SECONDS = 86400  # 24 hours
_CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
_FALLBACK_RATE = Decimal("95.0")


async def get_usd_to_rub_rate(redis: Any) -> Decimal:
    """Return the USD->RUB exchange rate.

    Checks Redis cache first (key ``fx:usd_rub``, TTL 24h).  On cache miss
    fetches from the CBR XML-daily JSON API.  On any CBR error falls back to
    a hardcoded rate of 95 and emits a warning log.
    """
    # Try cache first
    cached = await redis.get(_CACHE_KEY)
    if cached is not None:
        try:
            return Decimal(cached.decode() if isinstance(cached, bytes) else str(cached))
        except Exception:
            pass  # corrupted cache — refetch

    # Fetch from CBR
    rate: Decimal | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_CBR_URL)
            resp.raise_for_status()
            data = resp.json()
            usd_value = data["Valute"]["USD"]["Value"]
            rate = Decimal(str(usd_value))
    except Exception as exc:
        logger.warning(
            "CBR rate fetch failed, using fallback rate %s: %s",
            _FALLBACK_RATE,
            exc,
        )
        rate = _FALLBACK_RATE

    # Cache the result (even the fallback — prevents thundering herd on CBR outages)
    try:
        await redis.set(_CACHE_KEY, str(rate), ex=_CACHE_TTL_SECONDS)
    except Exception as cache_exc:
        logger.warning("Failed to cache FX rate: %s", cache_exc)

    return rate
