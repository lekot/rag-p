import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Dataset, Organization, Pipeline, Run
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_organization, require_scope
from ragp_api.services.usage import record_usage_event

router = APIRouter(tags=["runs"])


class RunCreateIn(BaseModel):
    query: str | None = None
    dataset_id: str | None = None


class RunOut(BaseModel):
    id: str
    organization_id: str
    pipeline_version_id: str
    dataset_id: str | None
    query: str | None
    status: str
    metrics: dict[str, Any] | None
    trace: dict[str, Any] | None = None
    answer: str | None = None
    contexts: list[dict[str, Any]] | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@router.post("/pipelines/{pipeline_id}/runs", status_code=202, response_model=RunOut)
async def create_run(
    pipeline_id: str,
    body: RunCreateIn,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> RunOut:
    pl_result = await db.execute(
        select(Pipeline).where(
            Pipeline.id == pipeline_id,
            Pipeline.organization_id == org.id,
        )
    )
    pipeline = pl_result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    if pipeline.current_version_id is None:
        raise HTTPException(status_code=422, detail="Pipeline has no version")

    from ragp_api.db.models import PipelineVersion

    ver_result = await db.execute(
        select(PipelineVersion).where(PipelineVersion.id == pipeline.current_version_id)
    )
    ver = ver_result.scalar_one_or_none()
    if ver is None or not ver.nodes_json:
        raise HTTPException(status_code=422, detail="Pipeline version has no nodes")

    org_id = org.id
    query = body.query or ""
    effective_dataset_id = pipeline.dataset_id
    if pipeline.dataset_id is not None:
        if body.dataset_id is not None and body.dataset_id != pipeline.dataset_id:
            raise HTTPException(
                status_code=422,
                detail="Run dataset_id must be absent or match the pipeline dataset_id",
            )
    elif body.dataset_id is not None:
        ds_result = await db.execute(
            select(Dataset).where(
                Dataset.id == body.dataset_id,
                Dataset.organization_id == org_id,
            )
        )
        if ds_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail=f"Dataset {body.dataset_id} not found")
        effective_dataset_id = body.dataset_id

    # Check subscription / quota before executing
    from ragp_api.services.subscription import (
        NoActiveSubscriptionError as _NoSub,
    )
    from ragp_api.services.subscription import (
        QuotaExceededError as _SubQuota,
    )
    from ragp_api.services.subscription import (
        consume_q as _consume_q,
    )
    from ragp_api.services.subscription import (
        get_active_subscription as _get_sub,
    )
    from ragp_api.services.subscription import (
        release_q as _release_q,
    )
    from ragp_api.settings import settings as _runs_settings

    quota_reserved = False
    if _runs_settings.enforce_subscription_quotas:
        no_active_plan_detail = {
            "code": "no_active_plan",
            "message": "No active subscription. Buy a plan at /pricing",
        }
        try:
            if await _get_sub(db, org_id) is None:
                raise HTTPException(status_code=402, detail=no_active_plan_detail)
        except _NoSub:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "no_active_plan",
                    "message": "Активной подписки нет. Купите план на /pricing",
                },
            ) from None
        try:
            await _consume_q(db, org_id, count=1)
            quota_reserved = True
        except _NoSub:
            raise HTTPException(status_code=402, detail=no_active_plan_detail) from None
        except _SubQuota as exc:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "quota_exceeded",
                    "q_used": exc.q_used,
                    "q_limit": exc.q_limit,
                    "message": "Лимит RAG-запросов исчерпан. Перейдите на старший тариф.",
                },
            ) from None

    run = Run(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        pipeline_version_id=pipeline.current_version_id,
        dataset_id=effective_dataset_id,
        query=query,
        status="running",
        started_at=datetime.now(),
    )
    db.add(run)
    await db.commit()

    # Execute pipeline inline
    try:
        from ragp_api.services.pipeline_runner import run_pipeline

        enriched_nodes: list[dict[str, Any]] = []
        for node in ver.nodes_json:
            n = dict(node)
            if n.get("plugin_kind") == "retriever":
                params = dict(n.get("params", {}))
                params["session"] = db
                params["organization_id"] = org_id
                params["dataset_id"] = effective_dataset_id
                n["params"] = params
            enriched_nodes.append(n)

        result = await run_pipeline(enriched_nodes, query, db)

        usage_dict: dict[str, Any] = result.get("usage", {})
        prompt_tokens = int(usage_dict.get("prompt_tokens", 0))
        completion_tokens = int(usage_dict.get("completion_tokens", 0))
        answer = result.get("answer", "")
        contexts = result.get("contexts", [])
        run.status = "completed"
        run.finished_at = datetime.now()
        run.metrics_json = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        run.traces_json = {
            "answer": answer,
            "contexts": [
                {"id": c.get("id", ""), "text": c.get("text", "")[:300]} for c in contexts
            ],
            "traces": result.get("traces", []),
        }
        await db.commit()
        model = "pipeline-run"
        for node in ver.nodes_json:
            if node.get("plugin_kind") == "generator":
                params = node.get("params") or {}
                if isinstance(params, dict) and params.get("model"):
                    model = str(params["model"])
                break
        await record_usage_event(
            db,
            org_id=org_id,
            api_key_id=None,
            pipeline_id=pipeline.id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            quota_reserved=_runs_settings.enforce_subscription_quotas,
        )
        await db.refresh(run)
    except Exception:
        run.status = "failed"
        run.finished_at = datetime.now()
        if quota_reserved:
            await _release_q(db, org_id, count=1)
        await db.commit()
        await db.refresh(run)

    traces_raw = run.traces_json or {}
    return RunOut(
        id=run.id,
        organization_id=run.organization_id,
        pipeline_version_id=run.pipeline_version_id,
        dataset_id=run.dataset_id,
        query=run.query,
        status=run.status,
        metrics=run.metrics_json,
        trace=traces_raw,
        answer=traces_raw.get("answer"),
        contexts=traces_raw.get("contexts"),
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("read")),
) -> RunOut:
    result = await db.execute(
        select(Run).where(
            Run.id == run_id,
            Run.organization_id == org.id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    traces_raw = run.traces_json or {}
    return RunOut(
        id=run.id,
        organization_id=run.organization_id,
        pipeline_version_id=run.pipeline_version_id,
        dataset_id=run.dataset_id,
        query=run.query,
        status=run.status,
        metrics=run.metrics_json,
        trace=traces_raw,
        answer=traces_raw.get("answer"),
        contexts=traces_raw.get("contexts"),
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    dataset_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("read")),
) -> list[RunOut]:
    stmt = select(Run).where(Run.organization_id == org.id)
    if dataset_id is not None:
        stmt = stmt.where(Run.dataset_id == dataset_id)
    stmt = stmt.order_by(Run.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    return [
        RunOut(
            id=r.id,
            organization_id=r.organization_id,
            pipeline_version_id=r.pipeline_version_id,
            dataset_id=r.dataset_id,
            query=r.query,
            status=r.status,
            metrics=r.metrics_json,
            trace=(r.traces_json or {}),
            answer=(r.traces_json or {}).get("answer"),
            contexts=(r.traces_json or {}).get("contexts"),
            started_at=r.started_at,
            finished_at=r.finished_at,
            created_at=r.created_at,
        )
        for r in runs
    ]
