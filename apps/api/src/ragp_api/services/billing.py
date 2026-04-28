"""Billing service — balance management and transaction recording.

All balance mutations use SELECT FOR UPDATE (on PostgreSQL) to prevent
double-spend races.  On SQLite (unit tests) row-level locking is not
available; the optimistic path still keeps the logic correct for single-
threaded test scenarios.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import BillingTransaction, OrgBalance

logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Raised when balance is too low for requested operation."""

    def __init__(self, balance: Decimal, required: Decimal) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient balance: have {balance}, need {required}")


async def get_balance(db: AsyncSession, org_id: str) -> Decimal:
    """Return current balance for org_id.  Returns Decimal('0') if no record."""
    result = await db.execute(select(OrgBalance).where(OrgBalance.org_id == org_id))
    row = result.scalar_one_or_none()
    if row is None:
        return Decimal("0")
    return Decimal(str(row.balance_usd))


async def deduct_balance(
    db: AsyncSession,
    *,
    org_id: str,
    amount: Decimal,
    reference_type: str,
    reference_id: str | None,
    allow_negative: bool = False,
) -> Decimal:
    """Atomically deduct *amount* from org balance.

    Uses SELECT FOR UPDATE on PostgreSQL.  Raises InsufficientBalanceError if
    the balance would go below zero and allow_negative is False.

    Returns the new (post-deduction) balance.
    Inserts a billing_transactions row.
    """
    # SELECT FOR UPDATE — locks the row for the duration of this transaction.
    # with_for_update() is a no-op on SQLite (tests), harmless on Postgres.
    result = await db.execute(
        select(OrgBalance).where(OrgBalance.org_id == org_id).with_for_update()
    )
    balance_row = result.scalar_one_or_none()

    current = Decimal(str(balance_row.balance_usd)) if balance_row else Decimal("0")

    if not allow_negative and current < amount:
        raise InsufficientBalanceError(balance=current, required=amount)

    new_balance = current - amount

    if balance_row is None:
        balance_row = OrgBalance(
            org_id=org_id,
            balance_usd=new_balance,
            updated_at=datetime.now(UTC),
        )
        db.add(balance_row)
    else:
        balance_row.balance_usd = new_balance
        balance_row.updated_at = datetime.now(UTC)

    tx = BillingTransaction(
        id=str(uuid.uuid4()),
        org_id=org_id,
        type="deduction",
        amount_usd=amount,
        balance_after_usd=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=None,
        note=None,
    )
    db.add(tx)
    await db.flush()

    return new_balance


async def topup_balance(
    db: AsyncSession,
    *,
    org_id: str,
    amount: Decimal,
    tx_type: str = "topup",
    created_by: str | None,
    note: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> Decimal:
    """Increase org balance by *amount*.

    Inserts a billing_transactions row.  Returns the new balance.

    ``reference_type`` and ``reference_id`` are optional; when omitted the
    defaults are derived from ``tx_type`` for backwards compatibility.
    """
    result = await db.execute(
        select(OrgBalance).where(OrgBalance.org_id == org_id).with_for_update()
    )
    balance_row = result.scalar_one_or_none()

    current = Decimal(str(balance_row.balance_usd)) if balance_row else Decimal("0")
    new_balance = current + amount

    if balance_row is None:
        balance_row = OrgBalance(
            org_id=org_id,
            balance_usd=new_balance,
            updated_at=datetime.now(UTC),
        )
        db.add(balance_row)
    else:
        balance_row.balance_usd = new_balance
        balance_row.updated_at = datetime.now(UTC)

    # Derive defaults for backwards compatibility
    if reference_type is None:
        reference_type = "system" if tx_type == "starting_credit" else "manual_topup"

    tx = BillingTransaction(
        id=str(uuid.uuid4()),
        org_id=org_id,
        type=tx_type,
        amount_usd=amount,
        balance_after_usd=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
        note=note,
    )
    db.add(tx)
    await db.flush()

    return new_balance
