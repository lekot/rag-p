"""Public RAG query endpoint -- authenticated via API key (Bearer token)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Dataset, Organization, Pipeline, PipelineVersion, Plan, Run
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.deps_auth import get_api_key_org, require_scope
from ragp_api.plugins.base import Embedder, Generator, Retriever
from ragp_api.plugins.registry import get_plugin
from ragp_api.services.audit import log_audit_event
from ragp_api.services.pipeline_runner import run_pipeline
from ragp_api.services.rate_limiter import (
    QueryQuotaReservation,
    check_rag_query_limits,
    release_rag_query_quota,
)
from ragp_api.services.usage import calculate_cost, record_usage_event
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

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
    cost_usd: float = 0.0


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


async def _check_limits_and_commit_quota(
    redis: Any,
    db: AsyncSession,
    org_id: str,
    api_key_id: str,
) -> QueryQuotaReservation:
    reservation = await check_rag_query_limits(redis, org_id, api_key_id, settings, db)
    if reservation.reserved:
        await db.commit()
    return reservation


async def _resolve_embedder() -> tuple[Embedder | None, str]:
    """Return (embedder, embedder_name) using environment priority: OpenAI → Cohere → Ollama."""
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if openai_key:
        cls = get_plugin("embedder", "litellm-embedder")
        if cls is not None:
            return (
                cast(Embedder, cls({"model": "openai/text-embedding-3-small"})),
                "litellm-embedder",
            )
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
    elif ollama_host:
        cls = get_plugin("embedder", "ollama-embedder")
        if cls is not None:
            return cast(Embedder, cls({"model": "bge-m3"})), "ollama-embedder"
    return None, "none"


# ---------------------------------------------------------------------------
# POST /rag/query
# ---------------------------------------------------------------------------


@router.post("/query", response_model=RagQueryOut)
async def rag_query(
    body: RagQueryIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: tuple[Organization, ApiKey] | None = Depends(get_api_key_org),
    redis: Any = Depends(get_redis),
    _scope: None = Depends(require_scope("read")),
) -> RagQueryOut:
    """RAG query endpoint for programmatic (API-key-authenticated) access."""

    # 1. Auth: require valid Bearer API key
    if auth is None:
        raise HTTPException(status_code=401, detail="Valid API key required")
    org, api_key = auth

    _request_start = time.monotonic()

    # 2. Load and verify dataset ownership before consuming paid query quota.
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
        quota_reservation = await _check_limits_and_commit_quota(redis, db, org.id, api_key.id)
        query_completed = False

        try:
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
            query_completed = True
            finished_at = datetime.now(tz=UTC)

            raw_chunks: list[dict[str, Any]] = result.get("contexts", [])
            answer: str = result.get("answer", "")
            rag_usage_dict: dict[str, Any] = result.get("usage", {})
            rag_prompt_tokens = int(rag_usage_dict.get("prompt_tokens", 0))
            rag_completion_tokens = int(rag_usage_dict.get("completion_tokens", 0))
        except Exception:
            if not query_completed:
                await release_rag_query_quota(db, quota_reservation)
            raise

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

        await log_audit_event(
            db,
            org_id=org.id,
            user_id=api_key.user_id,
            event_type="rag.query",
            resource_type="api_key",
            resource_id=api_key.id,
            metadata={"pipeline_id": body.pipeline_id},
            request=request,
        )
        await db.commit()

        # Determine model used by pipeline generator node
        pipeline_model = next(
            (
                n.get("params", {}).get("model", default_model)
                for n in pipeline_nodes
                if n.get("plugin_kind") == "generator"
            ),
            default_model,
        )
        pipeline_cost = calculate_cost(pipeline_model, rag_prompt_tokens, rag_completion_tokens)
        pipeline_latency_ms = int((time.monotonic() - _request_start) * 1000)

        try:
            await record_usage_event(
                db,
                org_id=org.id,
                api_key_id=api_key.id,
                pipeline_id=body.pipeline_id,
                model=pipeline_model,
                prompt_tokens=rag_prompt_tokens,
                completion_tokens=rag_completion_tokens,
                latency_ms=pipeline_latency_ms,
                quota_reserved=quota_reservation.reserved,
            )
        except Exception:
            logger.warning("Usage recording failed (pipeline path)", exc_info=True)

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
                cost_usd=float(pipeline_cost),
            ),
            trace=RagTrace(
                embedder="pipeline",
                retriever="pipeline",
                generator="pipeline",
                model=pipeline_model,
            ),
        )

    # 4. Default path: embed -> retrieve -> generate
    quota_reservation = await _check_limits_and_commit_quota(redis, db, org.id, api_key.id)
    query_completed = False
    try:
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
            query_completed = True
            empty_latency_ms = int((time.monotonic() - _request_start) * 1000)
            try:
                await record_usage_event(
                    db,
                    org_id=org.id,
                    api_key_id=api_key.id,
                    pipeline_id=None,
                    model=default_model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=empty_latency_ms,
                    quota_reserved=quota_reservation.reserved,
                )
            except Exception:
                logger.warning("Usage recording failed (empty default path)", exc_info=True)

            await log_audit_event(
                db,
                org_id=org.id,
                user_id=api_key.user_id,
                event_type="rag.query",
                resource_type="api_key",
                resource_id=api_key.id,
                metadata={"pipeline_id": None},
                request=request,
            )
            await db.commit()

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
        query_completed = True
    except Exception:
        if not query_completed:
            await release_rag_query_quota(db, quota_reservation)
        raise

    answer = gen_result.get("answer", "")
    trace_raw: dict[str, Any] = gen_result.get("trace", {})
    usage_raw: dict[str, Any] = trace_raw.get("usage", {})

    default_prompt_tokens = int(usage_raw.get("prompt_tokens", 0))
    default_completion_tokens = int(usage_raw.get("completion_tokens", 0))
    default_cost = calculate_cost(default_model, default_prompt_tokens, default_completion_tokens)
    default_latency_ms = int((time.monotonic() - _request_start) * 1000)

    try:
        await record_usage_event(
            db,
            org_id=org.id,
            api_key_id=api_key.id,
            pipeline_id=None,
            model=default_model,
            prompt_tokens=default_prompt_tokens,
            completion_tokens=default_completion_tokens,
            latency_ms=default_latency_ms,
            quota_reserved=quota_reservation.reserved,
        )
    except Exception:
        logger.warning("Usage recording failed (default path)", exc_info=True)

    await log_audit_event(
        db,
        org_id=org.id,
        user_id=api_key.user_id,
        event_type="rag.query",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"pipeline_id": None},
        request=request,
    )
    await db.commit()

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
            prompt_tokens=default_prompt_tokens,
            completion_tokens=default_completion_tokens,
            cost_usd=float(default_cost),
        ),
        trace=RagTrace(
            embedder=embedder_name,
            retriever="pgvector-hybrid",
            generator="litellm-generator",
            model=default_model,
        ),
    )


class UsageQuotaOut(BaseModel):
    remaining_queries: int
    total_quota: int | None
    plan_name: str | None
    has_active_subscription: bool


@router.get("/usage/quota", response_model=UsageQuotaOut)
async def get_usage_quota(
    db: AsyncSession = Depends(get_db),
    auth: tuple[Organization, ApiKey] | None = Depends(get_api_key_org),
    redis: Any = Depends(get_redis),
) -> UsageQuotaOut:
    """Return remaining query quota for the authenticated API key's org.

    Authentication: API Key (same as /rag/query).
    Response includes remaining queries in the current window and plan info.
    """
    from sqlalchemy import select

    from ragp_api.services.subscription import get_active_subscription

    if auth is None:
        raise HTTPException(status_code=401, detail="API key required")

    org, api_key = auth

    if not settings.enforce_subscription_quotas:
        return UsageQuotaOut(
            remaining_queries=-1,
            total_quota=None,
            plan_name=None,
            has_active_subscription=True,
        )

    try:
        sub = await get_active_subscription(db, org.id)
    except Exception:
        sub = None

    if sub is None:
        return UsageQuotaOut(
            remaining_queries=0,
            total_quota=0,
            plan_name=None,
            has_active_subscription=False,
        )

    plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    plan = plan_result.scalar_one_or_none()
    rpm_limit = (
        plan.rpm_per_key if plan and plan.rpm_per_key > 0 else settings.rate_limit_per_key_rpm
    )
    plan_name = plan.name if plan else None

    # Count current usage in the sliding window
    key_redis_key = f"rl:key:{api_key.id}"
    try:
        now_ms = time.time()
        window_start = now_ms - 60
        count = await redis.zcount(key_redis_key, window_start, now_ms) if redis else 0
    except Exception:
        count = 0

    remaining = max(0, rpm_limit - count)

    return UsageQuotaOut(
        remaining_queries=remaining,
        total_quota=rpm_limit if rpm_limit < 1e9 else None,
        plan_name=plan_name,
        has_active_subscription=True,
    )
