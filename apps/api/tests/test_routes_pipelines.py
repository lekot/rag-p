import uuid

import pytest
from httpx import AsyncClient

from ragp_api.settings import settings


@pytest.fixture(autouse=True)
def _stub_pipeline_plugins(monkeypatch) -> None:
    class _Plugin:
        pass

    def _get_plugin(_plugin_kind: str, plugin_name: str):
        if plugin_name == "nonexistent-chunker":
            return None
        return _Plugin

    from ragp_api.api.v1 import routes_pipelines

    monkeypatch.setattr(routes_pipelines, "get_plugin", _get_plugin)


async def _signup(client: AsyncClient, org_name: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"{org_name}-{uuid.uuid4().hex}@example.com",
            "password": "s3cr3t!",
            "organization_name": org_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_pipeline_valid(client: AsyncClient, organization_id: str):
    response = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
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
        headers={"X-Organization-Id": organization_id},
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
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Pipeline A",
            "organization_id": organization_id,
            "nodes": [
                {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}
            ],
        },
    )
    response = await client.get(
        f"/api/v1/pipelines?organization_id={organization_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(p["organization_id"] == organization_id for p in data)


@pytest.mark.asyncio
async def test_get_pipeline_not_found(client: AsyncClient):
    response = await client.get(
        "/api/v1/pipelines/nonexistent-id",
        headers={"X-Organization-Id": "org-test-001"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_run_for_pipeline(client: AsyncClient, organization_id: str):
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
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
        headers={"X-Organization-Id": organization_id},
        json={"query": "What is RAG?"},
    )
    assert run_resp.status_code == 202
    run_data = run_resp.json()
    assert run_data["id"]
    assert run_data["status"] == "failed"  # inline exec fails without real LLM in test


@pytest.mark.asyncio
async def test_create_run_without_active_subscription_returns_no_active_plan(
    client: AsyncClient,
    organization_id: str,
) -> None:
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Quota Pipeline",
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
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    old_enforce_subscription_quotas = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        run_resp = await client.post(
            f"/api/v1/pipelines/{pipeline_id}/runs",
            headers={"X-Organization-Id": organization_id},
            json={"query": "What is RAG?"},
        )
    finally:
        settings.enforce_subscription_quotas = old_enforce_subscription_quotas

    assert run_resp.status_code == 402, run_resp.text
    assert run_resp.json()["detail"]["code"] == "no_active_plan"


@pytest.mark.asyncio
async def test_pipeline_routes_scope_to_session_org_not_client_supplied_org(
    client: AsyncClient,
) -> None:
    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        tenant_a = await _signup(client, "pipelines-tenant-a")
        tenant_a_org_id = tenant_a["organization"]["id"]

        create_resp = await client.post(
            "/api/v1/pipelines",
            json={
                "name": "Tenant A Pipeline",
                "organization_id": "other-org",
                "nodes": [
                    {
                        "plugin_kind": "chunker",
                        "plugin_name": "recursive-character",
                        "params": {},
                    }
                ],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        pipeline_id = create_resp.json()["id"]
        assert create_resp.json()["organization_id"] == tenant_a_org_id

        await client.post("/api/v1/auth/logout")
        tenant_b = await _signup(client, "pipelines-tenant-b")
        tenant_b_org_id = tenant_b["organization"]["id"]

        list_resp = await client.get(f"/api/v1/pipelines?organization_id={tenant_a_org_id}")
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json() == []

        create_b_resp = await client.post(
            "/api/v1/pipelines",
            json={
                "name": "Tenant B Pipeline",
                "organization_id": tenant_a_org_id,
                "nodes": [
                    {
                        "plugin_kind": "chunker",
                        "plugin_name": "recursive-character",
                        "params": {},
                    }
                ],
            },
        )
        assert create_b_resp.status_code == 201, create_b_resp.text
        assert create_b_resp.json()["organization_id"] == tenant_b_org_id

        assert (await client.get(f"/api/v1/pipelines/{pipeline_id}")).status_code == 404
        assert (
            await client.put(
                f"/api/v1/pipelines/{pipeline_id}",
                json={"name": "Cross Org Update"},
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/pipelines/{pipeline_id}/promote",
                json={"experiment_id": str(uuid.uuid4())},
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/pipelines/{pipeline_id}/runs",
                json={"query": "cross org"},
            )
        ).status_code == 404
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header


@pytest.mark.asyncio
async def test_run_routes_scope_to_session_org_not_query_org(
    client: AsyncClient,
    db_session,
) -> None:
    from ragp_api.db.models import Pipeline, PipelineVersion, Run

    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        tenant_a = await _signup(client, "runs-tenant-a")
        tenant_a_org_id = tenant_a["organization"]["id"]
        version = PipelineVersion(
            id=str(uuid.uuid4()),
            pipeline_id=str(uuid.uuid4()),
            nodes_json=[{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}],
        )
        pipeline = Pipeline(
            id=version.pipeline_id,
            organization_id=tenant_a_org_id,
            name="Tenant A Run Pipeline",
            current_version_id=version.id,
        )
        run = Run(
            id=str(uuid.uuid4()),
            organization_id=tenant_a_org_id,
            pipeline_version_id=version.id,
            query="tenant a run",
            status="completed",
        )
        db_session.add_all([pipeline, version, run])
        await db_session.commit()

        await client.post("/api/v1/auth/logout")
        await _signup(client, "runs-tenant-b")

        list_resp = await client.get(f"/api/v1/runs?organization_id={tenant_a_org_id}")
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json() == []
        assert (await client.get(f"/api/v1/runs/{run.id}")).status_code == 404
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header
