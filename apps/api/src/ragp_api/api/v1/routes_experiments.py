import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Experiment, Organization, Pipeline, PipelineVersion
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_organization, require_scope
from ragp_api.services.audit import log_audit_event
from ragp_api.services.queue import QuotaExceededError, enqueue

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentCreateIn(BaseModel):
    name: str
    dataset_id: str
    plugin_grid: dict[str, list[dict[str, Any]]]


class ExperimentOut(BaseModel):
    id: str
    name: str
    organization_id: str
    dataset_id: str
    status: str
    plugin_grid: dict[str, list[dict[str, Any]]] | None = None
    leaderboard: list[Any] | None = None
    created_at: datetime | None = None


class LeaderboardScoresOut(BaseModel):
    faithfulness: float | None = None
    answer_relevance: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    retrieval_hit: float | None = None
    hit_rate: float | None = None
    context_relevance: float | None = None
    answer_similarity: float | None = None


class LeaderboardCombinationOut(BaseModel):
    config: dict[str, Any]
    scores: LeaderboardScoresOut
    composite_score: float
    status: str = "completed"
    error_code: str | None = None
    error: str | None = None
    warning: str | None = None
    nodes: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []


class LeaderboardOut(BaseModel):
    experiment_id: str
    status: str
    leaderboard: list[Any]
    combinations: list[LeaderboardCombinationOut]


class PromoteIn(BaseModel):
    name: str
    combination_index: int = 0


class PipelineNodeOut(BaseModel):
    plugin_kind: str
    plugin_name: str
    params: dict[str, Any] = {}


class PipelineOut(BaseModel):
    id: str
    name: str
    organization_id: str
    current_version_id: str | None
    dataset_id: str | None = None
    nodes: list[PipelineNodeOut] = []


@router.post("", status_code=201, response_model=ExperimentOut)
async def create_experiment(
    body: ExperimentCreateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> ExperimentOut:
    experiment = Experiment(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        name=body.name,
        dataset_id=body.dataset_id,
        plugin_grid_json=body.plugin_grid,
        status="queued",
    )
    db.add(experiment)
    await db.flush()
    await log_audit_event(
        db,
        org_id=org.id,
        user_id=None,
        event_type="experiment.start",
        resource_type="experiment",
        resource_id=experiment.id,
        metadata={"name": body.name, "dataset_id": body.dataset_id},
        request=request,
    )
    await db.commit()
    await db.refresh(experiment)

    # Enqueue to ARQ worker — POST returns immediately (~50 ms).
    # Poll GET /experiments/{id} until status != "queued"/"running".
    try:
        await enqueue(
            task_type="experiment.run",
            tenant_id=org.id,
            payload={"experiment_id": experiment.id},
            idempotency_key=f"experiment.run:{experiment.id}",
            queue_name="rag.experiment",
        )
    except QuotaExceededError as e:
        raise HTTPException(
            status_code=429,
            detail="quota_exceeded",
            headers={"Retry-After": str(int(e.retry_after_seconds))},
        ) from e

    return ExperimentOut(
        id=experiment.id,
        name=experiment.name,
        organization_id=experiment.organization_id,
        dataset_id=experiment.dataset_id,
        status=experiment.status,
        plugin_grid=experiment.plugin_grid_json,
        leaderboard=experiment.leaderboard_json,
        created_at=experiment.created_at,
    )


@router.get("", response_model=list[ExperimentOut])
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("read")),
) -> list[ExperimentOut]:
    result = await db.execute(
        select(Experiment).where(Experiment.organization_id == org.id)
    )
    experiments = result.scalars().all()
    return [
        ExperimentOut(
            id=e.id,
            name=e.name,
            organization_id=e.organization_id,
            dataset_id=e.dataset_id,
            status=e.status,
            plugin_grid=e.plugin_grid_json,
            leaderboard=e.leaderboard_json,
            created_at=e.created_at,
        )
        for e in experiments
    ]


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("read")),
) -> ExperimentOut:
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.organization_id == org.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return ExperimentOut(
        id=experiment.id,
        name=experiment.name,
        organization_id=experiment.organization_id,
        dataset_id=experiment.dataset_id,
        status=experiment.status,
        plugin_grid=experiment.plugin_grid_json,
        leaderboard=experiment.leaderboard_json,
        created_at=experiment.created_at,
    )


@router.get("/{experiment_id}/leaderboard", response_model=LeaderboardOut)
async def get_leaderboard(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("read")),
) -> LeaderboardOut:
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.organization_id == org.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")

    raw_leaderboard = experiment.leaderboard_json or []

    # Normalise to LeaderboardCombination shape for frontend compatibility
    combinations = []
    for entry in raw_leaderboard:
        if "error" in entry:
            continue
        nodes = entry.get("nodes", [])
        metrics = entry.get("metrics", {})
        composite = entry.get("composite_score", metrics.get("composite_score", 0.0))
        config: dict[str, Any] = {f"{n['plugin_kind']}": n["plugin_name"] for n in nodes}
        combinations.append(
            LeaderboardCombinationOut(
                config=config,
                scores=LeaderboardScoresOut(
                    faithfulness=metrics.get("faithfulness"),
                    answer_relevance=metrics.get("answer_relevance")
                    or metrics.get("answer_similarity"),
                    context_precision=metrics.get("context_precision"),
                    context_recall=metrics.get("context_recall")
                    or metrics.get("retrieval_hit")
                    or metrics.get("context_relevance"),
                    retrieval_hit=metrics.get("retrieval_hit"),
                    hit_rate=metrics.get("hit_rate"),
                    context_relevance=metrics.get("context_relevance"),
                    answer_similarity=metrics.get("answer_similarity"),
                ),
                composite_score=composite,
                status=metrics.get("status", "completed"),
                error_code=metrics.get("error_code"),
                error=metrics.get("error"),
                warning=metrics.get("warning"),
                nodes=nodes,
                traces=entry.get("traces", []),
            )
        )

    return LeaderboardOut(
        experiment_id=experiment_id,
        status=experiment.status,
        leaderboard=raw_leaderboard,
        combinations=combinations,
    )


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> None:
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if experiment is None or experiment.organization_id != org.id:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    await db.delete(experiment)
    await log_audit_event(
        db,
        org_id=org.id,
        user_id=None,
        event_type="experiment.delete",
        resource_type="experiment",
        resource_id=experiment_id,
        metadata={"name": experiment.name},
        request=request,
    )
    await db.commit()


@router.post("/{experiment_id}/promote_to_pipeline", status_code=201, response_model=PipelineOut)
async def promote_to_pipeline(
    experiment_id: str,
    body: PromoteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> PipelineOut:
    result = await db.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.organization_id == org.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    if experiment.status != "completed":
        raise HTTPException(
            status_code=422,
            detail=f"Experiment is not completed (status={experiment.status})",
        )

    leaderboard = experiment.leaderboard_json or []
    # Filter out error entries
    valid_entries = [e for e in leaderboard if "error" not in e]
    if not valid_entries:
        raise HTTPException(status_code=422, detail="Leaderboard is empty or all runs failed")

    idx = body.combination_index
    if idx < 0 or idx >= len(valid_entries):
        raise HTTPException(
            status_code=422,
            detail=f"combination_index {idx} out of range (0-{len(valid_entries)-1})",
        )

    selected_entry = valid_entries[idx]
    nodes: list[dict[str, Any]] = selected_entry.get("nodes", [])

    pipeline_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    version = PipelineVersion(
        id=version_id,
        pipeline_id=pipeline_id,
        nodes_json=nodes,
    )
    pipeline = Pipeline(
        id=pipeline_id,
        organization_id=experiment.organization_id,
        name=body.name,
        dataset_id=experiment.dataset_id,
        current_version_id=version_id,
    )

    db.add(version)
    db.add(pipeline)
    await db.flush()
    await log_audit_event(
        db,
        org_id=experiment.organization_id,
        user_id=None,
        event_type="experiment.promote",
        resource_type="experiment",
        resource_id=experiment_id,
        metadata={"pipeline_id": pipeline_id, "pipeline_name": body.name},
        request=request,
    )
    await db.commit()
    await db.refresh(pipeline)

    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        organization_id=pipeline.organization_id,
        current_version_id=pipeline.current_version_id,
        dataset_id=pipeline.dataset_id,
        nodes=[PipelineNodeOut(**n) for n in nodes],
    )
