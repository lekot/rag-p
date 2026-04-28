"""Billing endpoints — balance inquiry and manual top-up."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import BillingTransaction, OrgRole
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_session_user
from ragp_api.db.models import User
from ragp_api.services.audit import log_audit_event
from ragp_api.services.billing import get_balance, topup_balance
from ragp_api.services.permissions import require_role

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
