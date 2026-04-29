"""YooKassa payment gateway client.

Handles payment creation (with NPD receipt) and webhook payload parsing.
YooKassa does not support HMAC webhook signatures; security relies on:
  1. IP allowlist (YooKassa IP ranges)
  2. Idempotency — one payment_id -> one billing_transactions row
     enforced by a UNIQUE partial index (see migration 0010_yookassa).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from yookassa import Configuration, Payment  # type: ignore[import-untyped]
from yookassa.domain.notification import WebhookNotification  # type: ignore[import-untyped]

from ragp_api.services.fx import get_usd_to_rub_rate
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_YOOKASSA_API_BASE = "https://api.yookassa.ru/v3"


class PaymentRevalidationError(RuntimeError):
    """Raised when YooKassa refuses or fails to return a payment object."""


def _configure() -> None:
    """Apply YooKassa SDK configuration from application settings."""
    Configuration.account_id = settings.yookassa_shop_id
    Configuration.secret_key = settings.yookassa_secret_key


async def create_payment(
    *,
    org_id: UUID,
    user_email: str,
    amount_usd: Decimal,
    redis: Any,
) -> tuple[str, str, Decimal]:
    """Create a YooKassa payment with an NPD fiscal receipt (overage / wallet top-up).

    Returns a tuple of ``(payment_id, confirmation_url, amount_rub)``.

    The RUB amount is calculated as:
        amount_rub = amount_usd * cbr_rate * (1 + markup)
    rounded to 2 decimal places.
    """
    _configure()

    rate = await get_usd_to_rub_rate(redis)
    markup_factor = Decimal("1") + settings.usd_to_rub_markup
    amount_rub = (amount_usd * rate * markup_factor).quantize(Decimal("0.01"))

    receipt: dict[str, Any] = {
        "customer": {"email": user_email},
        "items": [
            {
                "description": f"RAG-Platform credit ${amount_usd}",
                "quantity": "1.00",
                "amount": {"value": str(amount_rub), "currency": "RUB"},
                "vat_code": 1,  # no VAT (NPD / self-employed)
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
        "tax_system_code": settings.yookassa_taxation_system,  # 6 = NPD
    }

    payment_data: dict[str, Any] = {
        "amount": {"value": str(amount_rub), "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": settings.yookassa_return_url,
        },
        "capture": True,
        "description": f"Top up for org {org_id}",
        "metadata": {
            "org_id": str(org_id),
            "amount_usd": str(amount_usd),
            "type": "topup",
        },
        "receipt": receipt,
    }

    payment = Payment.create(payment_data)
    return payment.id, payment.confirmation.confirmation_url, amount_rub


async def create_payment_rub(
    *,
    org_id: UUID,
    user_email: str,
    amount_rub: Decimal,
    description: str,
    metadata: dict[str, str],
    redis: Any,
) -> tuple[str, str, Decimal]:
    """Create a YooKassa payment for a fixed RUB amount (subscription plans).

    Returns a tuple of ``(payment_id, confirmation_url, amount_rub)``.
    """
    _configure()

    receipt: dict[str, Any] = {
        "customer": {"email": user_email},
        "items": [
            {
                "description": description,
                "quantity": "1.00",
                "amount": {"value": str(amount_rub), "currency": "RUB"},
                "vat_code": 1,  # no VAT (NPD / self-employed)
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
        "tax_system_code": settings.yookassa_taxation_system,  # 6 = NPD
    }

    payment_data: dict[str, Any] = {
        "amount": {"value": str(amount_rub), "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": settings.yookassa_return_url,
        },
        "capture": True,
        "description": description,
        "metadata": metadata,
        "receipt": receipt,
    }

    payment = Payment.create(payment_data)
    return payment.id, payment.confirmation.confirmation_url, amount_rub


async def fetch_payment_status(payment_id: str) -> dict[str, Any]:
    """Fetch the authoritative payment object from YooKassa.

    Performs ``GET /v3/payments/{id}`` against ``api.yookassa.ru`` using HTTP
    Basic Auth (``shop_id`` + ``secret_key``).  TLS to the official endpoint
    is the cryptographic anchor — even without HMAC on the webhook itself,
    a forged webhook cannot match this re-fetched payload.

    Returns the parsed JSON object on 2xx, retrying once on 5xx.  Raises
    :class:`PaymentRevalidationError` on any other failure (network error,
    4xx, malformed JSON, missing credentials).
    """
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise PaymentRevalidationError("yookassa credentials are not configured")

    url = f"{_YOOKASSA_API_BASE}/payments/{payment_id}"
    auth = (settings.yookassa_shop_id, settings.yookassa_secret_key)
    timeout = httpx.Timeout(settings.yookassa_revalidate_timeout_seconds)
    last_status: int | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            try:
                response = await client.get(url, auth=auth)
            except httpx.HTTPError as exc:
                if attempt == 0:
                    logger.warning(
                        "fetch_payment_status: transport error on attempt %d: %s",
                        attempt + 1,
                        exc,
                    )
                    continue
                raise PaymentRevalidationError(
                    f"transport error contacting YooKassa: {exc}"
                ) from exc

            last_status = response.status_code
            if 200 <= response.status_code < 300:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise PaymentRevalidationError(
                        "yookassa returned malformed JSON"
                    ) from exc
                if not isinstance(data, dict):
                    raise PaymentRevalidationError("yookassa response is not an object")
                return data

            if response.status_code >= 500 and attempt == 0:
                logger.warning(
                    "fetch_payment_status: YooKassa 5xx on attempt 1, retrying: %s",
                    response.status_code,
                )
                continue
            break

    raise PaymentRevalidationError(
        f"yookassa returned non-success status: {last_status}"
    )


def parse_webhook(raw_body: bytes, headers: dict[str, str]) -> WebhookNotification:
    """Parse and return a YooKassa webhook notification.

    YooKassa does not support HMAC signatures.  The caller is responsible for
    IP-level filtering.  This function only validates that the payload is a
    well-formed WebhookNotification.

    Raises ``ValueError`` on malformed payload.
    """
    import json

    try:
        data = json.loads(raw_body)
        notification = WebhookNotification(data)
    except Exception as exc:
        raise ValueError(f"Invalid YooKassa webhook payload: {exc}") from exc

    return notification
