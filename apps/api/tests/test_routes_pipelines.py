import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_pipeline_valid(client: AsyncClient, organization_id: str):
    response = await client.post(
        "/api/v1/pipelines",
        json={
            "name": "Test Pipeline",
            "organization_id": organization_id,
            "nodes": [
                {
                    "plugin_kind": "chunker",
                    "plugin_name": "recursive-character",
                    "params": {"chunk_size": 512, "chunk_overlap": 64},
                }
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Pipeline"
    assert data["organization_id"] == organization_id
    assert data["id"]
    assert data["current_version_id"]


@pytest.mark.asyncio
async def test_create_pipeline_invalid_plugin_name(client: AsyncClient, organization_id: str):
    response = await client.post(
        "/api/v1/pipelines",
        json={
            "name": "Bad Pipeline",
            "organization_id": organization_id,
            "nodes": [
                {
                    "plugin_kind": "chunker",
                    "plugin_name": "nonexistent-chunker",
                    "params": {},
                }
            ],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_pipelines(client: AsyncClient, organization_id: str):
    await client.post(
        "/api/v1/pipelines",
        json={
            "name": "Pipeline A",
            "organization_id": organization_id,
            "nodes": [
                {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}
            ],
        },
    )
    response = await client.get(f"/api/v1/pipelines?organization_id={organization_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(p["organization_id"] == organization_id for p in data)


@pytest.mark.asyncio
async def test_get_pipeline_not_found(client: AsyncClient):
    response = await client.get("/api/v1/pipelines/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_run_for_pipeline(client: AsyncClient, organization_id: str):
    create_resp = await client.post(
        "/api/v1/pipelines",
        json={
            "name": "Run Pipeline",
            "organization_id": organization_id,
            "nodes": [
                {
                    "plugin_kind": "generator",
                    "plugin_name": "litellm-generator",
                    "params": {"model": "openai/gpt-4o-mini"},
                }
            ],
        },
    )
    assert create_resp.status_code == 201
    pipeline_id = create_resp.json()["id"]

    run_resp = await client.post(
        f"/api/v1/pipelines/{pipeline_id}/runs",
        json={"query": "What is RAG?"},
    )
    assert run_resp.status_code == 202
    run_data = run_resp.json()
    assert run_data["id"]
    assert run_data["status"] == "failed"  # inline exec fails without real LLM in test
