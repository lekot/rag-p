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

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

from ragp_api.services.fx import get_usd_to_rub_rate
from ragp_api.settings import settings

logger = logging.getLogger(__name__)


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
    """Create a YooKassa payment with an NPD fiscal receipt.

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
                "vat_code": 1,          # no VAT (NPD / self-employed)
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
        },
        "receipt": receipt,
    }

    payment = Payment.create(payment_data)
    return payment.id, payment.confirmation.confirmation_url, amount_rub


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
