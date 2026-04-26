import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Pipeline, PipelineVersion, Run
from ragp_api.deps import get_db

router = APIRouter(tags=["runs"])


class RunCreateIn(BaseModel):
    query: str | None = None
    dataset_id: str | None = None


class RunOut(BaseModel):
    id: str
    status: str
    pipeline_version_id: str
    organization_id: str


@router.post("/pipelines/{pipeline_id}/runs", status_code=202, response_model=RunOut)
async def create_run(
    pipeline_id: str,
    body: RunCreateIn,
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    if pipeline.current_version_id is None:
        raise HTTPException(status_code=422, detail="Pipeline has no version")

    run = Run(
        id=str(uuid.uuid4()),
        organization_id=pipeline.organization_id,
        pipeline_version_id=pipeline.current_version_id,
        dataset_id=body.dataset_id,
        query=body.query,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # TODO: enqueue async execution via background task / queue
    return RunOut(
        id=run.id,
        status=run.status,
        pipeline_version_id=run.pipeline_version_id,
        organization_id=run.organization_id,
    )


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> RunOut:
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunOut(
        id=run.id,
        status=run.status,
        pipeline_version_id=run.pipeline_version_id,
        organization_id=run.organization_id,
    )


@router.get("/runs", response_model=list[RunOut])
async def list_runs(organization_id: str, db: AsyncSession = Depends(get_db)) -> list[RunOut]:
    result = await db.execute(select(Run).where(Run.organization_id == organization_id))
    runs = result.scalars().all()
    return [
        RunOut(
            id=r.id,
            status=r.status,
            pipeline_version_id=r.pipeline_version_id,
            organization_id=r.organization_id,
        )
        for r in runs
    ]
