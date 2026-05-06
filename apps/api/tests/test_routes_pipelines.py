import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ragp_api.db.models import Dataset, OrgSubscription, Plan, UsageEvent
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


async def _grant_test_subscription(
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
    *,
    plan_id: str = "pipeline-run-test",
    included_q: int = 100,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Plan(
            id=plan_id,
            name="Pipeline Run Test",
            price_rub_monthly=Decimal("100"),
            included_q=included_q,
            included_storage_bytes=10_000_000,
            max_users=1,
            rpm_per_key=60,
            allow_overage=False,
            is_active=True,
            sort_order=1,
        )
    )
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=organization_id,
            plan_id=plan_id,
            status="active",
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()


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
@pytest.mark.parametrize("dataset_id", [str(uuid.uuid4()), "foreign"])
async def test_create_pipeline_rejects_missing_or_foreign_dataset_id(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
    dataset_id: str,
) -> None:
    if dataset_id == "foreign":
        dataset_id = str(uuid.uuid4())
        db_session.add(
            Dataset(
                id=dataset_id,
                organization_id="other-org",
                name="Foreign DS",
                source="uploaded",
            )
        )
        await db_session.commit()

    response = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Pipeline With Bad Dataset",
            "nodes": [
                {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}
            ],
            "dataset_id": dataset_id,
        },
    )

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset_id", [str(uuid.uuid4()), "foreign"])
async def test_update_pipeline_rejects_missing_or_foreign_dataset_id(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
    dataset_id: str,
) -> None:
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Pipeline To Update",
            "nodes": [
                {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    if dataset_id == "foreign":
        dataset_id = str(uuid.uuid4())
        db_session.add(
            Dataset(
                id=dataset_id,
                organization_id="other-org",
                name="Foreign DS",
                source="uploaded",
            )
        )
        await db_session.commit()

    response = await client.put(
        f"/api/v1/pipelines/{pipeline_id}",
        headers={"X-Organization-Id": organization_id},
        json={"dataset_id": dataset_id},
    )

    assert response.status_code == 404, response.text


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
async def test_create_run_records_usage_event_without_double_consuming_reserved_quota(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    await _grant_test_subscription(db_session, organization_id)
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Usage Pipeline",
            "nodes": [
                {
                    "plugin_kind": "generator",
                    "plugin_name": "litellm-generator",
                    "params": {"model": "deepseek/deepseek-v4-flash"},
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        with patch(
            "ragp_api.services.pipeline_runner.run_pipeline",
            new=AsyncMock(
                return_value={
                    "answer": "ok",
                    "contexts": [],
                    "traces": [],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                }
            ),
        ):
            run_resp = await client.post(
                f"/api/v1/pipelines/{pipeline_id}/runs",
                headers={"X-Organization-Id": organization_id},
                json={"query": "What changed?"},
            )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert run_resp.status_code == 202, run_resp.text
    assert run_resp.json()["status"] == "completed"

    db_session.expire_all()
    subscription = (
        await db_session.execute(
            select(OrgSubscription).where(OrgSubscription.org_id == organization_id)
        )
    ).scalar_one()
    assert subscription.q_used == 1

    usage_events = (
        (
            await db_session.execute(
                select(UsageEvent).where(
                    UsageEvent.org_id == organization_id,
                    UsageEvent.pipeline_id == pipeline_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(usage_events) == 1
    assert usage_events[0].prompt_tokens == 12
    assert usage_events[0].completion_tokens == 3


@pytest.mark.asyncio
async def test_create_run_releases_reserved_quota_when_inline_pipeline_fails(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    await _grant_test_subscription(db_session, organization_id)
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Failing Run Pipeline",
            "nodes": [
                {
                    "plugin_kind": "generator",
                    "plugin_name": "litellm-generator",
                    "params": {"model": "deepseek/deepseek-v4-flash"},
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        with patch(
            "ragp_api.services.pipeline_runner.run_pipeline",
            new=AsyncMock(side_effect=RuntimeError("LLM unavailable")),
        ):
            run_resp = await client.post(
                f"/api/v1/pipelines/{pipeline_id}/runs",
                headers={"X-Organization-Id": organization_id},
                json={"query": "What changed?"},
            )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert run_resp.status_code == 202, run_resp.text
    assert run_resp.json()["status"] == "failed"
    db_session.expire_all()
    subscription = (
        await db_session.execute(
            select(OrgSubscription).where(OrgSubscription.org_id == organization_id)
        )
    ).scalar_one()
    assert subscription.q_used == 0
    usage_events = (
        (
            await db_session.execute(
                select(UsageEvent).where(
                    UsageEvent.org_id == organization_id,
                    UsageEvent.pipeline_id == pipeline_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert usage_events == []


@pytest.mark.asyncio
async def test_create_run_uses_pipeline_dataset_binding_for_retrievers_and_run_record(
    client: AsyncClient,
    organization_id: str,
) -> None:
    dataset_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Bound Dataset", "organization_id": organization_id},
    )
    assert dataset_resp.status_code == 201, dataset_resp.text
    dataset_id = dataset_resp.json()["id"]
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Bound Dataset Pipeline",
            "dataset_id": dataset_id,
            "nodes": [
                {
                    "plugin_kind": "retriever",
                    "plugin_name": "qdrant-retriever",
                    "params": {"top_k": 3},
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    captured_nodes: list[dict] = []

    async def _run_pipeline(nodes, _query, _db):  # noqa: ANN001
        captured_nodes.extend(nodes)
        return {"answer": "ok", "contexts": [], "traces": [], "usage": {}}

    with patch("ragp_api.services.pipeline_runner.run_pipeline", new=_run_pipeline):
        run_resp = await client.post(
            f"/api/v1/pipelines/{pipeline_id}/runs",
            headers={"X-Organization-Id": organization_id},
            json={"query": "Use bound dataset"},
        )

    assert run_resp.status_code == 202, run_resp.text
    assert run_resp.json()["status"] == "completed"
    assert run_resp.json()["dataset_id"] == dataset_id
    retriever_params = captured_nodes[0]["params"]
    assert retriever_params["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_create_run_rejects_dataset_id_that_conflicts_with_pipeline_binding(
    client: AsyncClient,
    organization_id: str,
) -> None:
    bound_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Bound Dataset", "organization_id": organization_id},
    )
    other_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Other Dataset", "organization_id": organization_id},
    )
    assert bound_resp.status_code == 201, bound_resp.text
    assert other_resp.status_code == 201, other_resp.text
    bound_dataset_id = bound_resp.json()["id"]
    other_dataset_id = other_resp.json()["id"]
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Conflicting Dataset Pipeline",
            "dataset_id": bound_dataset_id,
            "nodes": [
                {
                    "plugin_kind": "retriever",
                    "plugin_name": "qdrant-retriever",
                    "params": {},
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    with patch("ragp_api.services.pipeline_runner.run_pipeline", new=AsyncMock()) as pipeline_mock:
        run_resp = await client.post(
            f"/api/v1/pipelines/{pipeline_id}/runs",
            headers={"X-Organization-Id": organization_id},
            json={"query": "bad dataset", "dataset_id": other_dataset_id},
        )

    assert run_resp.status_code == 422, run_resp.text
    pipeline_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_validates_body_dataset_for_unbound_pipeline(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    foreign_dataset_id = str(uuid.uuid4())
    db_session.add(
        Dataset(
            id=foreign_dataset_id,
            organization_id="other-org",
            name="Foreign Dataset",
            source="uploaded",
        )
    )
    await db_session.commit()
    create_resp = await client.post(
        "/api/v1/pipelines",
        headers={"X-Organization-Id": organization_id},
        json={
            "name": "Unbound Dataset Pipeline",
            "nodes": [
                {
                    "plugin_kind": "retriever",
                    "plugin_name": "qdrant-retriever",
                    "params": {},
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    pipeline_id = create_resp.json()["id"]

    with patch("ragp_api.services.pipeline_runner.run_pipeline", new=AsyncMock()) as pipeline_mock:
        run_resp = await client.post(
            f"/api/v1/pipelines/{pipeline_id}/runs",
            headers={"X-Organization-Id": organization_id},
            json={"query": "foreign dataset", "dataset_id": foreign_dataset_id},
        )

    assert run_resp.status_code == 404, run_resp.text
    pipeline_mock.assert_not_awaited()


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
            nodes_json=[
                {
                    "plugin_kind": "chunker",
                    "plugin_name": "recursive-character",
                    "params": {},
                }
            ],
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
        db_session.add_all([pipeline, version])
        await db_session.flush()
        db_session.add(run)
        await db_session.commit()

        await client.post("/api/v1/auth/logout")
        await _signup(client, "runs-tenant-b")

        list_resp = await client.get(f"/api/v1/runs?organization_id={tenant_a_org_id}")
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json() == []
        assert (await client.get(f"/api/v1/runs/{run.id}")).status_code == 404
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header
