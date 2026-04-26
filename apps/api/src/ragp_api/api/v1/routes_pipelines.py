import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.api.errors import PluginNotFoundError
from ragp_api.db.models import Pipeline, PipelineVersion
from ragp_api.deps import get_db
from ragp_api.plugins.registry import get_plugin

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineNodeIn(BaseModel):
    plugin_kind: str
    plugin_name: str
    params: dict[str, Any] = {}


class PipelineCreateIn(BaseModel):
    name: str
    organization_id: str
    nodes: list[PipelineNodeIn]


class PipelineOut(BaseModel):
    id: str
    name: str
    organization_id: str
    current_version_id: str | None


@router.post("", status_code=201, response_model=PipelineOut)
async def create_pipeline(
    body: PipelineCreateIn,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    # Validate all plugins exist before persisting
    for node in body.nodes:
        if get_plugin(node.plugin_kind, node.plugin_name) is None:
            raise PluginNotFoundError(node.plugin_kind, node.plugin_name)

    pipeline_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    nodes_json = [n.model_dump() for n in body.nodes]

    version = PipelineVersion(id=version_id, pipeline_id=pipeline_id, nodes_json=nodes_json)
    pipeline = Pipeline(
        id=pipeline_id,
        organization_id=body.organization_id,
        name=body.name,
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
    )


@router.get("", response_model=list[PipelineOut])
async def list_pipelines(
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[PipelineOut]:
    result = await db.execute(
        select(Pipeline).where(Pipeline.organization_id == organization_id)
    )
    pipelines = result.scalars().all()
    return [
        PipelineOut(
            id=p.id,
            name=p.name,
            organization_id=p.organization_id,
            current_version_id=p.current_version_id,
        )
        for p in pipelines
    ]


@router.get("/{pipeline_id}", response_model=PipelineOut)
async def get_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        organization_id=pipeline.organization_id,
        current_version_id=pipeline.current_version_id,
    )
