from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ragp_api.api.errors import (
    NotFoundError,
    PluginNotFoundError,
    not_found_handler,
    plugin_not_found_handler,
)
from ragp_api.api.v1 import (
    routes_auth,
    routes_datasets,
    routes_experiments,
    routes_keys,
    routes_orgs,
    routes_pipelines,
    routes_plugins,
    routes_rag,
    routes_runs,
)
from ragp_api.db.redis import close_redis_pool, create_redis_pool
from ragp_api.plugins.registry import bootstrap
from ragp_api.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bootstrap()
    app.state.redis = await create_redis_pool(settings.redis_host, settings.redis_port)
    try:
        yield
    finally:
        await close_redis_pool(app.state.redis)


app = FastAPI(
    title="RAG Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(NotFoundError, not_found_handler)  # type: ignore[arg-type]
app.add_exception_handler(PluginNotFoundError, plugin_not_found_handler)  # type: ignore[arg-type]

_v1_prefix = "/api/v1"

app.include_router(routes_auth.router, prefix=_v1_prefix)
app.include_router(routes_orgs.router)
app.include_router(routes_keys.router, prefix=_v1_prefix)
app.include_router(routes_pipelines.router, prefix=_v1_prefix)
app.include_router(routes_datasets.router, prefix=_v1_prefix)
app.include_router(routes_runs.router, prefix=_v1_prefix)
app.include_router(routes_experiments.router, prefix=_v1_prefix)
app.include_router(routes_plugins.router, prefix=_v1_prefix)
app.include_router(routes_rag.router, prefix=_v1_prefix)


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, Any]:
    return {"status": "ok"}
