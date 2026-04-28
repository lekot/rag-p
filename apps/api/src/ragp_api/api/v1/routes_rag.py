"""Public RAG query endpoint — authenticated via API key (Bearer token)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Dataset, Organization, Pipeline, PipelineVersion, Run
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.deps_auth import get_api_key_org
from ragp_api.plugins.base import Embedder, Generator, Retriever
from ragp_api.plugins.registry import get_plugin
from ragp_api.services.pipeline_runner import run_pipeline
from ragp_api.services.rate_limiter import check_rag_query_limits
from ragp_api.settings import settings

router = APIRouter(prefix="/rag", tags=["rag"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RagQueryIn(BaseModel):
    dataset_id: str
    query: str
    top_k: int = 5
    pipeline_id: str | None = None


class RagChunkOut(BaseModel):
    id: str
    text: str
    score: float
    document_id: str
    document_name: str


class RagUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class RagTrace(BaseModel):
    embedder: str
    retriever: str
    generator: str
    model: str


class RagQueryOut(BaseModel):
    answer: str
    chunks: list[RagChunkOut]
    usage: RagUsage
    trace: RagTrace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_default_trace(model: str) -> RagTrace:
    return RagTrace(
        embedder="auto",
        retriever="pgvector-hybrid",
        generator="litellm-generator",
        model=model,
    )


async def _resolve_embedder() -> tuple[Embedder | None, str]:
    """Return (embedder, embedder_name) using environment priority."""
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if ollama_host:
        cls = get_plugin("embedder", "ollama-embedder")
        if cls is not None:
            return cast(Embedder, cls({"model": "bge-m3"})), "ollama-embedder"
    elif cohere_key:
        cls = get_plugin("embedder", "cohere-embedder")
        if cls is not None:
            return (
                cast(
                    Embedder,
                    cls({"model": "embed-multilingual-v3.0", "input_type": "search_query"}),
                ),
                "cohere-embedder",
            )
    elif openai_key:
        cls = get_plugin("embedder", "litellm-embedder")
        if cls is not None:
            return (
                cast(Embedder, cls({"model": "openai/text-embedding-3-small"})),
                "litellm-embedder",
            )
    return None, "none"


# ---------------------------------------------------------------------------
# POST /rag/query
# ---------------------------------------------------------------------------


@router.post("/query", response_model=RagQueryOut)
async def rag_query(
    body: RagQueryIn,
    db: AsyncSession = Depends(get_db),
    auth: tuple[Organization, ApiKey] | None = Depends(get_api_key_org),
    redis: Any = Depends(get_redis),
) -> RagQueryOut:
    """RAG query endpoint for programmatic (API-key-authenticated) access."""

    # 1. Auth: require valid Bearer API key
    if auth is None:
        raise HTTPException(status_code=401, detail="Valid API key required")
    org, api_key = auth

    # 2. Rate limiting (per key + per org)
    await check_rag_query_limits(redis, org.id, api_key.id, settings)

    # 3. Load and verify dataset ownership
    ds_result = await db.execute(select(Dataset).where(Dataset.id == body.dataset_id))
    dataset = ds_result.scalar_one_or_none()
    if dataset is None or dataset.organization_id != org.id:
        raise HTTPException(status_code=404, detail=f"Dataset {body.dataset_id} not found")

    default_model = "deepseek/deepseek-v4-flash"

    # 4. Pipeline path
    if body.pipeline_id is not None:
        pl_result = await db.execute(select(Pipeline).where(Pipeline.id == body.pipeline_id))
        pl = pl_result.scalar_one_or_none()
        if pl is None or pl.organization_id != org.id or pl.dataset_id != body.dataset_id:
            raise HTTPException(
                status_code=404,
                detail=f"Pipeline {body.pipeline_id} not found for this dataset",
            )
        if pl.current_version_id is None:
            raise HTTPException(
                status_code=422, detail=f"Pipeline {body.pipeline_id} has no published version"
            )
        ver_result = await db.execute(
            select(PipelineVersion).where(PipelineVersion.id == pl.current_version_id)
        )
        ver = ver_result.scalar_one_or_none()
        if ver is None:
            raise HTTPException(status_code=422, detail="Pipeline version not found")

        pipeline_nodes: list[dict[str, Any]] = ver.nodes_json

        # Inject session + context into retriever nodes
        enriched: list[dict[str, Any]] = []
        for node in pipeline_nodes:
            n = dict(node)
            if n.get("plugin_kind") == "retriever":
                params = dict(n.get("params", {}))
                params["session"] = db
                params["organization_id"] = org.id
                params["dataset_id"] = body.dataset_id
                params.setdefault("top_k", body.top_k)
                n["params"] = params
            enriched.append(n)

        started_at = datetime.now(tz=UTC)
        result = await run_pipeline(enriched, body.query, db)
        finished_at = datetime.now(tz=UTC)

        raw_chunks: list[dict[str, Any]] = result.get("contexts", [])
        answer: str = result.get("answer", "")
        rag_usage_dict: dict[str, Any] = result.get("usage", {})
        rag_prompt_tokens = int(rag_usage_dict.get("prompt_tokens", 0))
        rag_completion_tokens = int(rag_usage_dict.get("completion_tokens", 0))

        # Persist Run record
        run_record = Run(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            pipeline_version_id=pl.current_version_id,
            dataset_id=body.dataset_id,
            query=body.query,
            status="completed",
            metrics_json={
                "prompt_tokens": rag_prompt_tokens,
                "completion_tokens": rag_completion_tokens,
            },
            traces_json={"traces": result.get("traces", [])},
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(run_record)
        await db.commit()

        if not raw_chunks and not answer:
            answer = "Не нашёл релевантных чанков для ответа."

        return RagQueryOut(
            answer=answer,
            chunks=[
                RagChunkOut(
                    id=c.get("id", ""),
                    text=c.get("text", ""),
                    score=round(c.get("score", 0.0), 4),
                    document_id=c.get("document_id", ""),
                    document_name=c.get("document_name", ""),
                )
                for c in raw_chunks
            ],
            usage=RagUsage(
                prompt_tokens=rag_prompt_tokens,
                completion_tokens=rag_completion_tokens,
            ),
            trace=RagTrace(
                embedder="pipeline",
                retriever="pipeline",
                generator="pipeline",
                model="pipeline",
            ),
        )

    # 4. Default path: embed → retrieve → generate
    embedder, embedder_name = await _resolve_embedder()

    query_vec: list[float] | None = None
    if embedder is not None:
        try:
            vecs = await embedder.embed([body.query])
            query_vec = vecs[0]
        except Exception:
            pass

    retriever_cls = get_plugin("retriever", "pgvector-hybrid")
    if retriever_cls is None:
        raise HTTPException(status_code=500, detail="pgvector-hybrid retriever not available")

    retriever = cast(Retriever, retriever_cls({"session": db}))
    raw_chunks = await retriever.retrieve(
        query=body.query,
        top_k=body.top_k,
        organization_id=org.id,
        dataset_id=body.dataset_id,
        query_vec=query_vec,
    )

    if not raw_chunks:
        return RagQueryOut(
            answer="Не нашёл релевантных чанков для ответа.",
            chunks=[],
            usage=RagUsage(prompt_tokens=0, completion_tokens=0),
            trace=_build_default_trace(default_model),
        )

    generator_cls = get_plugin("generator", "litellm-generator")
    if generator_cls is None:
        raise HTTPException(status_code=500, detail="litellm-generator not available")

    generator = cast(
        Generator,
        generator_cls({"model": default_model, "temperature": 0.0, "max_tokens": 1024}),
    )
    gen_result = await generator.generate(body.query, contexts=raw_chunks)

    answer = gen_result.get("answer", "")
    trace_raw: dict[str, Any] = gen_result.get("trace", {})
    usage_raw: dict[str, Any] = trace_raw.get("usage", {})

    return RagQueryOut(
        answer=answer,
        chunks=[
            RagChunkOut(
                id=c["id"],
                text=c["text"],
                score=round(c["score"], 4),
                document_id=c["document_id"],
                document_name=c["document_name"],
            )
            for c in raw_chunks
        ],
        usage=RagUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
        ),
        trace=RagTrace(
            embedder=embedder_name,
            retriever="pgvector-hybrid",
            generator="litellm-generator",
            model=default_model,
        ),
    )
