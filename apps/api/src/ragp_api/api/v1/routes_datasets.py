import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Dataset
from ragp_api.deps import get_db

router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetCreateIn(BaseModel):
    name: str
    organization_id: str
    source: str = "uploaded"


class DatasetOut(BaseModel):
    id: str
    name: str
    organization_id: str
    source: str


@router.post("", status_code=201, response_model=DatasetOut)
async def create_dataset(
    body: DatasetCreateIn,
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    dataset = Dataset(
        id=str(uuid.uuid4()),
        organization_id=body.organization_id,
        name=body.name,
        source=body.source,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        organization_id=dataset.organization_id,
        source=dataset.source,
    )


@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[DatasetOut]:
    result = await db.execute(
        select(Dataset).where(Dataset.organization_id == organization_id)
    )
    datasets = result.scalars().all()
    return [
        DatasetOut(id=d.id, name=d.name, organization_id=d.organization_id, source=d.source)
        for d in datasets
    ]


@router.post("/{dataset_id}/generate", status_code=202)
async def generate_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    # TODO: implement RAGAS auto-generation
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    return {"status": "accepted", "dataset_id": dataset_id, "message": "RAGAS generation queued"}
