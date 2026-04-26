import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Experiment
from ragp_api.deps import get_db

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
    status: str


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

    # TODO: enqueue cartesian-product runs via experiment_runner service
    return ExperimentOut(
        id=experiment.id,
        name=experiment.name,
        organization_id=experiment.organization_id,
        status=experiment.status,
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
    return {
        "experiment_id": experiment_id,
        "status": experiment.status,
        "leaderboard": experiment.leaderboard_json or [],
    }
