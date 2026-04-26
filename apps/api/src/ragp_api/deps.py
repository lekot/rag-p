from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_organization_id(x_organization_id: str = Header(...)) -> str:
    """Extract organization_id from X-Organization-Id header."""
    if not x_organization_id:
        raise HTTPException(status_code=400, detail="X-Organization-Id header required")
    return x_organization_id


async def get_current_user_id(x_user_id: str = Header(default="")) -> str | None:
    """Extract user_id from X-User-Id header (optional in MVP)."""
    return x_user_id or None
