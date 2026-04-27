import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Experiment, Pipeline, PipelineVersion
from ragp_api.deps import get_db
from ragp_api.services.experiment_runner import run_experiment_inline

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentCreateIn(BaseModel):
    name: str
    organization_id: str
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


class PromoteIn(BaseModel):
    name: str


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
    db: AsyncSession = Depends(get_db),
) -> ExperimentOut:
    experiment = Experiment(
        id=str(uuid.uuid4()),
        organization_id=body.organization_id,
        name=body.name,
        dataset_id=body.dataset_id,
        plugin_grid_json=body.plugin_grid,
        status="pending",
    )
    db.add(experiment)
    await db.commit()
    await db.refresh(experiment)

    # Run inline (synchronous, in-request; no Celery for prototype)
    # [BLOCKED-NIGHT-RUN] Switch to Celery/ARQ for production workloads
    await run_experiment_inline(experiment, db)
    await db.refresh(experiment)

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
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ExperimentOut]:
    result = await db.execute(
        select(Experiment).where(Experiment.organization_id == organization_id)
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
) -> ExperimentOut:
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
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


@router.get("/{experiment_id}/leaderboard")
async def get_leaderboard(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
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
            {
                "config": config,
                "scores": {
                    "faithfulness": metrics.get("faithfulness"),
                    "answer_relevance": metrics.get("answer_relevance"),
                    "context_precision": metrics.get("context_precision"),
                    "context_recall": metrics.get("context_recall"),
                },
                "composite_score": composite,
                "nodes": nodes,
            }
        )

    return {
        "experiment_id": experiment_id,
        "status": experiment.status,
        "leaderboard": raw_leaderboard,
        "combinations": combinations,
    }


@router.post("/{experiment_id}/promote_to_pipeline", status_code=201, response_model=PipelineOut)
async def promote_to_pipeline(
    experiment_id: str,
    body: PromoteIn,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    if experiment.status != "completed":
        raise HTTPException(
            status_code=422,
            detail=f"Experiment is not completed (status={experiment.status})",
        )

    leaderboard = experiment.leaderboard_json or []
    # Filter out error entries and pick top-1
    valid_entries = [e for e in leaderboard if "error" not in e]
    if not valid_entries:
        raise HTTPException(status_code=422, detail="Leaderboard is empty or all runs failed")

    top_entry = valid_entries[0]
    nodes: list[dict[str, Any]] = top_entry.get("nodes", [])

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
