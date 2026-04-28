"""Billing endpoints — balance inquiry, manual top-up, and YooKassa checkout."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import BillingTransaction, OrgRole, User
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.services.audit import log_audit_event
from ragp_api.services.billing import get_balance, topup_balance
from ragp_api.services.fx import get_usd_to_rub_rate
from ragp_api.services.permissions import require_role
from ragp_api.services.yookassa_client import create_payment

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])

_TRANSACTIONS_LIMIT = 50


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TransactionOut(BaseModel):
    id: str
    type: str
    amount_usd: float
    balance_after_usd: float
    reference_type: str | None
    reference_id: str | None
    note: str | None
    created_at: str


class BillingOut(BaseModel):
    balance_usd: float
    transactions: list[TransactionOut]


class TopupIn(BaseModel):
    amount_usd: float
    note: str | None = None

    @field_validator("amount_usd")
    @classmethod
    def positive_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount_usd must be positive")
        return v


class TopupOut(BaseModel):
    balance_usd: float
    transaction_id: str


# ---------------------------------------------------------------------------
# GET /api/v1/orgs/{org_id}/billing
# ---------------------------------------------------------------------------


@router.get("/api/v1/orgs/{org_id}/billing", response_model=BillingOut)
async def get_billing(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Return current balance and last 50 transactions. Requires member+."""
    await require_role(db, current_user.id, org_id, OrgRole.member)

    balance = await get_balance(db, org_id)

    result = await db.execute(
        select(BillingTransaction)
        .where(BillingTransaction.org_id == org_id)
        .order_by(BillingTransaction.created_at.desc())
        .limit(_TRANSACTIONS_LIMIT)
    )
    txs = result.scalars().all()

    return BillingOut(
        balance_usd=float(balance),
        transactions=[
            TransactionOut(
                id=tx.id,
                type=tx.type,
                amount_usd=float(tx.amount_usd),
                balance_after_usd=float(tx.balance_after_usd),
                reference_type=tx.reference_type,
                reference_id=tx.reference_id,
                note=tx.note,
                created_at=tx.created_at.isoformat() if tx.created_at else "",
            )
            for tx in txs
        ],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/orgs/{org_id}/billing/topup
# ---------------------------------------------------------------------------


@router.post("/api/v1/orgs/{org_id}/billing/topup", response_model=TopupOut, status_code=200)
async def topup(
    org_id: str,
    body: TopupIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Manual top-up by org owner.  Requires owner role."""
    await require_role(db, current_user.id, org_id, OrgRole.owner)

    amount = Decimal(str(body.amount_usd))
    new_balance = await topup_balance(
        db,
        org_id=org_id,
        amount=amount,
        tx_type="topup",
        created_by=current_user.id,
        note=body.note,
    )

    # Fetch the transaction we just created (last tx for this org of type topup)
    result = await db.execute(
        select(BillingTransaction)
        .where(
            BillingTransaction.org_id == org_id,
            BillingTransaction.type == "topup",
        )
        .order_by(BillingTransaction.created_at.desc())
        .limit(1)
    )
    tx = result.scalar_one_or_none()
    tx_id = tx.id if tx else ""

    await log_audit_event(
        db,
        org_id=org_id,
        user_id=current_user.id,
        event_type="billing.topup",
        resource_type="org_balance",
        resource_id=org_id,
        metadata={
            "amount_usd": float(amount),
            "balance_after_usd": float(new_balance),
        },
        request=request,
    )

    await db.commit()

    return TopupOut(balance_usd=float(new_balance), transaction_id=tx_id)


# ---------------------------------------------------------------------------
# POST /api/v1/orgs/{org_id}/billing/checkout  — initiate YooKassa payment
# ---------------------------------------------------------------------------


class CheckoutCreateIn(BaseModel):
    amount_usd: Decimal

    @field_validator("amount_usd")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v < Decimal("1") or v > Decimal("1000"):
            raise ValueError("amount_usd must be between 1 and 1000")
        return v


class CheckoutCreateOut(BaseModel):
    confirmation_url: str
    payment_id: str
    amount_rub: Decimal
    rate_usd_rub: Decimal


@router.post(
    "/api/v1/orgs/{org_id}/billing/checkout",
    response_model=CheckoutCreateOut,
    status_code=200,
)
async def create_checkout(
    org_id: str,
    body: CheckoutCreateIn,
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Create a YooKassa payment session.  Requires org owner role."""
    await require_role(db, current_user.id, org_id, OrgRole.owner)

    payment_id, confirmation_url, amount_rub = await create_payment(
        org_id=UUID(org_id),
        user_email=current_user.email,
        amount_usd=body.amount_usd,
        redis=redis,
    )

    rate = await get_usd_to_rub_rate(redis)

    return CheckoutCreateOut(
        confirmation_url=confirmation_url,
        payment_id=payment_id,
        amount_rub=amount_rub,
        rate_usd_rub=rate,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/billing/webhook/yookassa  — receive YooKassa payment events
# No auth — YooKassa calls this from its servers
# ---------------------------------------------------------------------------


@router.post("/api/v1/billing/webhook/yookassa", status_code=200)
async def yookassa_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Handle YooKassa payment.succeeded webhook.

    Security: IP-level filtering + idempotency (UNIQUE partial index on
    billing_transactions for reference_type = 'yookassa_payment').
    """
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc

    event = payload.get("event")
    obj = payload.get("object", {})
    payment_id = obj.get("id")

    if event != "payment.succeeded":
        # Ignore canceled, refunded, etc. for MVP
        return {"status": "ignored"}

    org_id_str = obj.get("metadata", {}).get("org_id")
    amount_usd_str = obj.get("metadata", {}).get("amount_usd")

    if not org_id_str or not amount_usd_str:
        raise HTTPException(status_code=400, detail="missing metadata")

    if not payment_id:
        raise HTTPException(status_code=400, detail="missing payment id")

    # Idempotency check: if already processed, return 200 without changes
    existing = await db.scalar(
        select(BillingTransaction).where(
            BillingTransaction.reference_type == "yookassa_payment",
            BillingTransaction.reference_id == payment_id,
        )
    )
    if existing:
        return {"status": "already_processed"}

    try:
        amount_usd = Decimal(amount_usd_str)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid amount_usd in metadata") from exc

    new_balance = await topup_balance(
        db,
        org_id=org_id_str,
        amount=amount_usd,
        tx_type="topup",
        created_by=None,  # automated system
        note=f"YooKassa payment {payment_id}",
        reference_type="yookassa_payment",
        reference_id=payment_id,
    )

    await db.commit()

    logger.info(
        "YooKassa payment %s processed for org %s: +$%s, balance=$%s",
        payment_id,
        org_id_str,
        amount_usd,
        new_balance,
    )

    return {"status": "ok", "balance_usd": float(new_balance)}
