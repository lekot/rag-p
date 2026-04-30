"""Password reset endpoints: forgot-password and reset-password."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.deps import get_db
from ragp_api.services import password_reset as svc

router = APIRouter(prefix="/auth", tags=["auth"])

_ALWAYS_OK = {"detail": "If the email is registered, a reset link has been sent"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Initiate a password reset.

    Always returns 200 regardless of whether the email is registered so that
    attackers cannot enumerate accounts.
    """
    await svc.request_reset(db, body.email)
    return _ALWAYS_OK


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Complete a password reset using the one-time token."""
    success = await svc.complete_reset(db, body.token, body.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    return {"detail": "ok"}
