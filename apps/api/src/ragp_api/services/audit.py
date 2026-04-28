"""Audit logging service.

All writes are fire-and-forget: failures are logged as warnings but never
propagate to the caller.  This guarantees that a DB hiccup in the audit
path cannot break the main request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import AuditEvent

logger = logging.getLogger(__name__)


async def log_audit_event(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: Optional[str],
    event_type: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Insert an audit record.

    Never raises -- fail-safe so that audit failures cannot break the main request.
    """
    try:
        ip: str | None = None
        ua: str | None = None
        if request is not None:
            if request.client is not None:
                ip = request.client.host
            ua = request.headers.get("user-agent")

        event = AuditEvent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip,
            user_agent=ua,
            metadata=metadata or {},
        )
        db.add(event)
        await db.flush()
    except Exception:
        logger.warning("audit log failed for event_type=%s", event_type, exc_info=True)
