from fastapi import Request
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: str) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class PluginNotFoundError(Exception):
    def __init__(self, kind: str, name: str) -> None:
        self.kind = kind
        self.name = name
        super().__init__(f"Plugin {kind}/{name} not found")


async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc), "resource": exc.resource, "id": exc.resource_id},
    )


async def plugin_not_found_handler(request: Request, exc: PluginNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "kind": exc.kind, "name": exc.name},
    )
