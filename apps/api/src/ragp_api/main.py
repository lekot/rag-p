from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ragp_api.api.errors import NotFoundError, PluginNotFoundError, not_found_handler, plugin_not_found_handler
from ragp_api.api.v1 import routes_pipelines, routes_datasets, routes_runs, routes_experiments, routes_plugins
from ragp_api.plugins.registry import bootstrap


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    bootstrap()
    yield


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

app.include_router(routes_pipelines.router, prefix=_v1_prefix)
app.include_router(routes_datasets.router, prefix=_v1_prefix)
app.include_router(routes_runs.router, prefix=_v1_prefix)
app.include_router(routes_experiments.router, prefix=_v1_prefix)
app.include_router(routes_plugins.router, prefix=_v1_prefix)


@app.get("/health")
@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}
