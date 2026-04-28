"""Role-based permission helpers for org members.

Role hierarchy (highest to lowest):
    owner > admin > member
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import OrgMember, OrgRole

_ROLE_RANK: dict[str, int] = {
    OrgRole.owner: 3,
    OrgRole.admin: 2,
    OrgRole.member: 1,
}


async def get_member_role(
    db: AsyncSession,
    user_id: str,
    org_id: str,
) -> OrgRole | None:
    """Return the role of user_id in org_id, or None if not a member."""
    result = await db.execute(
        select(OrgMember).where(
            OrgMember.user_id == user_id,
            OrgMember.org_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        return None
    try:
        return OrgRole(member.role)
    except ValueError:
        return None


async def require_role(
    db: AsyncSession,
    user_id: str,
    org_id: str,
    min_role: OrgRole,
) -> OrgRole:
    """Assert that user has at least min_role in org.

    Returns the actual role on success. Raises HTTP 403 otherwise.
    """
    role = await get_member_role(db, user_id, org_id)
    if role is None or _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return role
