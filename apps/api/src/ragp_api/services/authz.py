"""Permify authorization client — stub with interface for MVP."""

from typing import Any

import httpx

from ragp_api.settings import settings


class PermifyClient:
    """HTTP client for Permify authorization service."""

    def __init__(self, base_url: str | None = None, tenant_id: str | None = None) -> None:
        self.base_url = base_url or settings.permify_url
        self.tenant_id = tenant_id or settings.permify_tenant_id

    async def check(
        self,
        subject_type: str,
        subject_id: str,
        permission: str,
        object_type: str,
        object_id: str,
    ) -> bool:
        """Check if subject has permission on object. Returns True in MVP stub."""
        # TODO: make real HTTP call to Permify check API
        # POST /v1/tenants/{tenant}/permissions/check
        return True

    async def write_relationship(
        self,
        subject_type: str,
        subject_id: str,
        relation: str,
        object_type: str,
        object_id: str,
    ) -> None:
        """Write a relationship tuple to Permify."""
        # TODO: POST /v1/tenants/{tenant}/relationships/write
        pass


_client: PermifyClient | None = None


def get_authz_client() -> PermifyClient:
    global _client
    if _client is None:
        _client = PermifyClient()
    return _client
