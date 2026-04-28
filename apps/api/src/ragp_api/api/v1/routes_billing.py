"""Billing endpoints for balances, top-ups, subscriptions, and YooKassa webhooks."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import BillingTransaction, OrgRole, Plan, SubscriptionEvent, User
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.services.audit import log_audit_event
from ragp_api.services.billing import get_balance, topup_balance
from ragp_api.services.fx import get_usd_to_rub_rate
from ragp_api.services.permissions import require_role
from ragp_api.services.subscription import get_active_subscription, start_subscription
from ragp_api.services.yookassa_client import create_payment, create_payment_rub

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
    """Create a YooKassa payment session for overage top-up."""
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
# POST /api/v1/orgs/{org_id}/subscription/checkout  — subscribe to a plan
# ---------------------------------------------------------------------------


class SubscriptionCheckoutIn(BaseModel):
    plan_id: str


class SubscriptionCheckoutOut(BaseModel):
    confirmation_url: str
    payment_id: str
    amount_rub: Decimal
    plan_id: str


@router.post(
    "/api/v1/orgs/{org_id}/subscription/checkout",
    response_model=SubscriptionCheckoutOut,
    status_code=200,
)
async def subscription_checkout(
    org_id: str,
    body: SubscriptionCheckoutIn,
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Create a YooKassa payment to activate or renew a subscription plan.

    On payment success the webhook calls start_subscription().
    Requires org owner role.
    """
    await require_role(db, current_user.id, org_id, OrgRole.owner)

    # Validate plan exists
    plan_result = await db.execute(
        select(Plan).where(Plan.id == body.plan_id, Plan.is_active.is_(True))
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{body.plan_id}' not found")

    payment_id, confirmation_url, amount_rub = await create_payment_rub(
        org_id=UUID(org_id),
        user_email=current_user.email,
        amount_rub=plan.price_rub_monthly,
        description=f"Подписка {plan.name} на 30 дней",
        metadata={
            "org_id": str(org_id),
            "plan_id": body.plan_id,
            "type": "subscription",
        },
        redis=redis,
    )

    return SubscriptionCheckoutOut(
        confirmation_url=confirmation_url,
        payment_id=payment_id,
        amount_rub=amount_rub,
        plan_id=body.plan_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/orgs/{org_id}/subscription  — current subscription info
# ---------------------------------------------------------------------------


class PlanOut(BaseModel):
    id: str
    name: str
    price_rub_monthly: float
    included_q: int
    included_storage_bytes: int
    max_users: int
    rpm_per_key: int
    allow_overage: bool


class SubscriptionOut(BaseModel):
    plan: PlanOut
    status: str
    current_period_start: str
    current_period_end: str
    q_used: int
    q_limit: int
    storage_bytes_used: int
    storage_bytes_limit: int


@router.get(
    "/api/v1/orgs/{org_id}/subscription",
    response_model=SubscriptionOut | None,
)
async def get_subscription(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Return current subscription info. Returns null if no active subscription."""
    await require_role(db, current_user.id, org_id, OrgRole.member)

    sub = await get_active_subscription(db, org_id)
    if sub is None:
        return None

    plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        return None

    return SubscriptionOut(
        plan=PlanOut(
            id=plan.id,
            name=plan.name,
            price_rub_monthly=float(plan.price_rub_monthly),
            included_q=plan.included_q,
            included_storage_bytes=plan.included_storage_bytes,
            max_users=plan.max_users,
            rpm_per_key=plan.rpm_per_key,
            allow_overage=plan.allow_overage,
        ),
        status=sub.status,
        current_period_start=sub.current_period_start.isoformat(),
        current_period_end=sub.current_period_end.isoformat(),
        q_used=sub.q_used,
        q_limit=plan.included_q,
        storage_bytes_used=sub.storage_bytes_used,
        storage_bytes_limit=plan.included_storage_bytes,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/orgs/{org_id}/subscription/events
# ---------------------------------------------------------------------------


class SubscriptionEventOut(BaseModel):
    id: str
    plan_id: str
    event_type: str
    period_start: str | None
    period_end: str | None
    amount_rub: float | None
    created_at: str


@router.get(
    "/api/v1/orgs/{org_id}/subscription/events",
    response_model=list[SubscriptionEventOut],
)
async def list_subscription_events(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_session_user),
) -> Any:
    """Return subscription history events for the org."""
    await require_role(db, current_user.id, org_id, OrgRole.member)

    result = await db.execute(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.org_id == org_id)
        .order_by(SubscriptionEvent.created_at.desc())
        .limit(50)
    )
    events = result.scalars().all()
    return [
        SubscriptionEventOut(
            id=ev.id,
            plan_id=ev.plan_id,
            event_type=ev.event_type,
            period_start=ev.period_start.isoformat() if ev.period_start else None,
            period_end=ev.period_end.isoformat() if ev.period_end else None,
            amount_rub=float(ev.amount_rub) if ev.amount_rub is not None else None,
            created_at=ev.created_at.isoformat(),
        )
        for ev in events
    ]


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

    Dispatches to:
    - metadata.type == "subscription" → start_subscription()
    - metadata.type == "topup" (or absent) → topup_balance() (legacy overage flow)

    Idempotency is enforced with DB constraints; signature/IP filtering is
    deferred until YooKassa production webhook settings are finalized.
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

    metadata = obj.get("metadata", {})
    org_id_str = metadata.get("org_id")
    payment_type = metadata.get("type", "topup")

    if not org_id_str:
        raise HTTPException(status_code=400, detail="missing metadata.org_id")

    if not payment_id:
        raise HTTPException(status_code=400, detail="missing payment id")

    # ---- Subscription payment ----
    if payment_type == "subscription":
        plan_id = metadata.get("plan_id")
        if not plan_id:
            raise HTTPException(status_code=400, detail="missing metadata.plan_id")

        amount_rub_str = obj.get("amount", {}).get("value", "0")
        try:
            amount_rub = Decimal(amount_rub_str)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid payment amount") from exc

        # Idempotency: backed by a DB unique constraint on yookassa_payment_id.
        existing = await db.scalar(
            select(SubscriptionEvent).where(SubscriptionEvent.yookassa_payment_id == payment_id)
        )
        if existing:
            return {"status": "already_processed"}

        try:
            sub = await start_subscription(
                db,
                org_id=org_id_str,
                plan_id=plan_id,
                payment_id=payment_id,
                amount_rub=amount_rub,
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return {"status": "already_processed"}

        logger.info(
            "YooKassa subscription payment %s processed for org %s: plan=%s, period_end=%s",
            payment_id,
            org_id_str,
            plan_id,
            sub.current_period_end.isoformat(),
        )
        return {
            "status": "ok",
            "plan_id": plan_id,
            "period_end": sub.current_period_end.isoformat(),
        }

    # ---- Overage topup payment (legacy / Corp/Enterprise wallet top-up) ----
    amount_usd_str = metadata.get("amount_usd")
    if not amount_usd_str:
        raise HTTPException(status_code=400, detail="missing metadata.amount_usd")

    # Idempotency check
    existing_tx = await db.scalar(
        select(BillingTransaction).where(
            BillingTransaction.reference_type == "yookassa_payment",
            BillingTransaction.reference_id == payment_id,
        )
    )
    if existing_tx:
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
        created_by=None,
        note=f"YooKassa payment {payment_id}",
        reference_type="yookassa_payment",
        reference_id=payment_id,
    )

    await db.commit()

    logger.info(
        "YooKassa topup payment %s processed for org %s: +$%s, balance=$%s",
        payment_id,
        org_id_str,
        amount_usd,
        new_balance,
    )

    return {"status": "ok", "balance_usd": float(new_balance)}
