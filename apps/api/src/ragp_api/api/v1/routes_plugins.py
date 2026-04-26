from typing import Any

from fastapi import APIRouter

from ragp_api.plugins.registry import list_plugins

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("", response_model=list[dict[str, Any]])
async def get_plugins() -> list[dict[str, Any]]:
    """List all registered plugins with their params schema."""
    return list_plugins()
