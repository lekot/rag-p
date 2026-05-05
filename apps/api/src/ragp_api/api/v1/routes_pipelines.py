import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.api.errors import PluginNotFoundError
from ragp_api.db.models import Organization, Pipeline, PipelineVersion
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_organization, require_scope
from ragp_api.plugins.registry import get_plugin
from ragp_api.services.audit import log_audit_event

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineNodeIn(BaseModel):
    plugin_kind: str
    plugin_name: str
    params: dict[str, Any] = {}


class PipelineCreateIn(BaseModel):
    name: str
    organization_id: str
    nodes: list[PipelineNodeIn]
    dataset_id: str | None = None


class PipelineOut(BaseModel):
    id: str
    name: str
    organization_id: str
    current_version_id: str | None
    dataset_id: str | None = None
    nodes: list[PipelineNodeIn] = []


class PipelineUpdateIn(BaseModel):
    name: str | None = None
    nodes: list[PipelineNodeIn] | None = None


class PromoteIn(BaseModel):
    experiment_id: str


async def _load_nodes(db: AsyncSession, version_id: str | None) -> list[PipelineNodeIn]:
    if not version_id:
        return []
    result = await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))
    version = result.scalar_one_or_none()
    if version is None or not version.nodes_json:
        return []
    return [PipelineNodeIn(**n) for n in version.nodes_json]


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
        dataset_id=body.dataset_id,
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
        nodes=body.nodes,
    )


@router.get("", response_model=list[PipelineOut])
async def list_pipelines(
    organization_id: str,
    dataset_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PipelineOut]:
    query = select(Pipeline).where(Pipeline.organization_id == organization_id)
    if dataset_id is not None:
        query = query.where(Pipeline.dataset_id == dataset_id)
    result = await db.execute(query)
    pipelines = result.scalars().all()
    out: list[PipelineOut] = []
    for p in pipelines:
        nodes = await _load_nodes(db, p.current_version_id)
        out.append(
            PipelineOut(
                id=p.id,
                name=p.name,
                organization_id=p.organization_id,
                current_version_id=p.current_version_id,
                dataset_id=p.dataset_id,
                nodes=nodes,
            )
        )
    return out


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(
    pipeline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> None:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None or pipeline.organization_id != org.id:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    await db.delete(pipeline)
    await log_audit_event(
        db,
        org_id=org.id,
        user_id=None,
        event_type="pipeline.delete",
        resource_type="pipeline",
        resource_id=pipeline_id,
        metadata={"name": pipeline.name},
        request=request,
    )
    await db.commit()


@router.put("/{pipeline_id}", response_model=PipelineOut)
async def update_pipeline(
    pipeline_id: str,
    body: PipelineUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    """Update pipeline metadata and/or nodes (creates a new version)."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    if body.name is not None:
        pipeline.name = body.name

    if body.nodes is not None:
        # Validate all plugins exist before persisting
        for node in body.nodes:
            if get_plugin(node.plugin_kind, node.plugin_name) is None:
                raise PluginNotFoundError(node.plugin_kind, node.plugin_name)

        version_id = str(uuid.uuid4())
        nodes_json = [n.model_dump() for n in body.nodes]
        version = PipelineVersion(
            id=version_id, pipeline_id=pipeline_id, nodes_json=nodes_json
        )
        db.add(version)
        pipeline.current_version_id = version_id

    await db.commit()
    await db.refresh(pipeline)

    nodes = await _load_nodes(db, pipeline.current_version_id)
    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        organization_id=pipeline.organization_id,
        current_version_id=pipeline.current_version_id,
        dataset_id=pipeline.dataset_id,
        nodes=nodes,
    )


@router.get("/{pipeline_id}", response_model=PipelineOut)
async def get_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    nodes = await _load_nodes(db, pipeline.current_version_id)
    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        organization_id=pipeline.organization_id,
        current_version_id=pipeline.current_version_id,
        dataset_id=pipeline.dataset_id,
        nodes=nodes,
    )


@router.post("/{pipeline_id}/promote", response_model=PipelineOut)
async def promote_pipeline(
    pipeline_id: str,
    body: PromoteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PipelineOut:
    """Promote a pipeline version from an experiment."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    await log_audit_event(
        db,
        org_id=pipeline.organization_id,
        user_id=None,
        event_type="pipeline.promote",
        resource_type="pipeline",
        resource_id=pipeline_id,
        metadata={"experiment_id": body.experiment_id},
        request=request,
    )
    await db.commit()

    nodes = await _load_nodes(db, pipeline.current_version_id)
    return PipelineOut(
        id=pipeline.id,
        name=pipeline.name,
        organization_id=pipeline.organization_id,
        current_version_id=pipeline.current_version_id,
        dataset_id=pipeline.dataset_id,
        nodes=nodes,
    )
