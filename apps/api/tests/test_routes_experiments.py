"""Tests for experiment routes and pipeline promotion."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from ragp_api.services.experiment_runner import build_combinations
from ragp_api.settings import settings

# ---------------------------------------------------------------------------
# Helper: mock the queue.enqueue() helper so tests don't need a real Redis.
# ---------------------------------------------------------------------------


def _make_enqueue_mock(experiment_id: str | None = None) -> AsyncMock:
    """Return an AsyncMock that mimics services.queue.enqueue() return value."""
    mock = AsyncMock(
        return_value={
            "job_id": "mock-job-id",
            "task_id": experiment_id or "mock-task-id",
            "deduplicated": False,
        }
    )
    return mock


async def _create_dataset(client: AsyncClient, organization_id: str) -> str:
    resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Test Dataset", "organization_id": organization_id},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


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


PLUGIN_GRID = {
    "chunkers": [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}],
    "embedders": [{"plugin_kind": "embedder", "plugin_name": "litellm-embedder", "params": {}}],
    "retrievers": [{"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}}],
    "generators": [
        {
            "plugin_kind": "generator",
            "plugin_name": "litellm-generator",
            "params": {"model": "openai/gpt-4o-mini"},
        }
    ],
}

PLUGIN_GRID_WITHOUT_EMBEDDER = {
    "chunkers": PLUGIN_GRID["chunkers"],
    "retrievers": PLUGIN_GRID["retrievers"],
    "generators": PLUGIN_GRID["generators"],
}


def test_build_combinations_accepts_frontend_name_alias() -> None:
    combinations = build_combinations(
        {
            "retrievers": [{"name": "pgvector-hybrid", "params": {"top_k": 3}}],
            "generators": [{"name": "litellm-generator", "params": {"max_tokens": 256}}],
        }
    )

    assert combinations == [
        [
            {
                "plugin_kind": "retriever",
                "plugin_name": "pgvector-hybrid",
                "params": {"top_k": 3},
            },
            {
                "plugin_kind": "generator",
                "plugin_name": "litellm-generator",
                "params": {"max_tokens": 256},
            },
        ]
    ]


def _make_redis_pool_mock() -> MagicMock:
    """Return a mock that behaves like an arq ArqRedis pool.

    Kept for tests that still need to mock the ARQ pool directly (e.g. in
    services/queue unit tests).  Route tests now patch ``services.queue.enqueue``
    directly instead.
    """
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock())
    pool.aclose = AsyncMock()
    pool.__aenter__ = AsyncMock(return_value=pool)
    pool.__aexit__ = AsyncMock(return_value=None)
    return pool


@pytest.mark.asyncio
async def test_experiment_enqueued_returns_queued_status(client: AsyncClient, organization_id: str):
    """POST /experiments should persist experiment with status='queued' and enqueue the job."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        response = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Queued Experiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["name"] == "Queued Experiment"
    assert data["dataset_id"] == dataset_id
    assert data["status"] == "queued"

    # Verify enqueue was called with experiment.run task type
    enqueue_mock.assert_awaited_once()
    call_kwargs = enqueue_mock.call_args.kwargs
    assert call_kwargs["task_type"] == "experiment.run"
    assert call_kwargs["tenant_id"] == organization_id
    assert call_kwargs["payload"]["experiment_id"] == data["id"]


@pytest.mark.asyncio
async def test_create_experiment_enqueues_job(client: AsyncClient, organization_id: str):
    """POST /experiments enqueues 'run_experiment_task' via queue.enqueue()."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        response = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Test Experiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    enqueue_mock.assert_awaited_once()
    call_kwargs = enqueue_mock.call_args.kwargs
    assert call_kwargs["task_type"] == "experiment.run"
    assert call_kwargs["payload"]["experiment_id"] == data["id"]


@pytest.mark.asyncio
async def test_create_experiment_enqueue_called_once(client: AsyncClient, organization_id: str):
    """enqueue() is called exactly once per POST /experiments request."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Once Test",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    assert enqueue_mock.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset_id", [str(uuid.uuid4()), "foreign"])
async def test_create_experiment_rejects_unowned_dataset_id(
    client: AsyncClient,
    organization_id: str,
    dataset_id: str,
) -> None:
    if dataset_id == "foreign":
        dataset_id = await _create_dataset(client, "other-org")
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        response = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Unowned Dataset Experiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    assert response.status_code == 404
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_experiment_requires_embedder_slot(
    client: AsyncClient,
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        response = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Missing Embedder Experiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID_WITHOUT_EMBEDDER,
            },
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_plugin_grid"
    assert detail["missing"] == ["embedders"]
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_experiments_org_filtered(client: AsyncClient, organization_id: str):
    """GET /experiments?organization_id=... returns only org's experiments."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Exp 1",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )
        await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": "other-org"},
            json={
                "name": "Exp 2",
                "organization_id": "other-org",
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    list_resp = await client.get(
        f"/api/v1/experiments?organization_id={organization_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert all(e["organization_id"] == organization_id for e in data)
    assert any(e["name"] == "Exp 1" for e in data)
    assert not any(e["name"] == "Exp 2" for e in data)


@pytest.mark.asyncio
async def test_get_experiment_by_id(client: AsyncClient, organization_id: str):
    """GET /experiments/{id} returns full experiment including plugin_grid."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        create_resp = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Detailed Exp",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    exp_id = create_resp.json()["id"]
    resp = await client.get(
        f"/api/v1/experiments/{exp_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == exp_id
    assert data["plugin_grid"] is not None
    # status is queued immediately after POST
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_promote_to_pipeline_requires_completed(client: AsyncClient, organization_id: str):
    """POST /experiments/{id}/promote_to_pipeline returns 422 when status != 'completed'."""
    dataset_id = await _create_dataset(client, organization_id)
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        create_resp = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Not Completed",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    exp_id = create_resp.json()["id"]

    promote_resp = await client.post(
        f"/api/v1/experiments/{exp_id}/promote_to_pipeline",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Should Fail"},
    )
    assert promote_resp.status_code == 422


@pytest.mark.asyncio
async def test_promote_to_pipeline(client: AsyncClient, organization_id: str, db_session):
    """POST /experiments/{id}/promote_to_pipeline creates pipeline with dataset_id.

    We simulate a completed experiment by directly updating the DB record.
    """
    from ragp_api.db.models import Experiment

    dataset_id = await _create_dataset(client, organization_id)

    winning_nodes = [
        {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}},
        {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}},
    ]

    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        create_resp = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "Promotable Exp",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    exp_id = create_resp.json()["id"]

    # Simulate worker completing the experiment by patching DB directly
    from sqlalchemy import select

    result = await db_session.execute(select(Experiment).where(Experiment.id == exp_id))
    experiment = result.scalar_one()
    experiment.status = "completed"
    experiment.leaderboard_json = [
        {"nodes": winning_nodes, "metrics": {"composite_score": 0.9}, "composite_score": 0.9}
    ]
    await db_session.commit()

    promote_resp = await client.post(
        f"/api/v1/experiments/{exp_id}/promote_to_pipeline",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Winner Pipeline"},
    )
    assert promote_resp.status_code == 201
    pipeline_data = promote_resp.json()
    assert pipeline_data["id"]
    assert pipeline_data["name"] == "Winner Pipeline"
    assert pipeline_data["dataset_id"] == dataset_id
    assert pipeline_data["nodes"] == winning_nodes


@pytest.mark.asyncio
async def test_pipeline_list_filter_by_dataset(
    client: AsyncClient, organization_id: str, db_session
):
    """GET /pipelines?dataset_id=... filters by dataset."""
    from sqlalchemy import select

    from ragp_api.db.models import Experiment

    # Create two datasets
    ds1_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "DS1", "organization_id": organization_id},
    )
    ds1_id = ds1_resp.json()["id"]
    ds2_resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": "DS2", "organization_id": organization_id},
    )
    ds2_id = ds2_resp.json()["id"]

    winning_nodes = [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}]
    enqueue_mock = _make_enqueue_mock()

    with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
        exp_resp = await client.post(
            "/api/v1/experiments",
            headers={"X-Organization-Id": organization_id},
            json={
                "name": "DS1 Exp",
                "organization_id": organization_id,
                "dataset_id": ds1_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    exp_id = exp_resp.json()["id"]

    # Simulate worker completing
    result = await db_session.execute(select(Experiment).where(Experiment.id == exp_id))
    experiment = result.scalar_one()
    experiment.status = "completed"
    experiment.leaderboard_json = [
        {"nodes": winning_nodes, "metrics": {"composite_score": 0.9}, "composite_score": 0.9}
    ]
    await db_session.commit()

    await client.post(
        f"/api/v1/experiments/{exp_id}/promote_to_pipeline",
        headers={"X-Organization-Id": organization_id},
        json={"name": "Pipeline for DS1"},
    )

    # Get pipelines filtered by ds1
    list_resp = await client.get(
        f"/api/v1/pipelines?organization_id={organization_id}&dataset_id={ds1_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert list_resp.status_code == 200
    pipelines = list_resp.json()
    assert len(pipelines) >= 1
    assert all(p["dataset_id"] == ds1_id for p in pipelines)

    # ds2 should return empty
    list_resp2 = await client.get(
        f"/api/v1/pipelines?organization_id={organization_id}&dataset_id={ds2_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert list_resp2.status_code == 200
    assert list_resp2.json() == []


@pytest.mark.asyncio
async def test_experiment_routes_scope_to_session_org_not_client_supplied_org(
    client: AsyncClient,
) -> None:
    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        tenant_a = await _signup(client, "experiments-tenant-a")
        tenant_a_org_id = tenant_a["organization"]["id"]
        dataset_id = await _create_dataset(client, tenant_a_org_id)
        enqueue_mock = _make_enqueue_mock()

        with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_mock):
            create_resp = await client.post(
                "/api/v1/experiments",
                json={
                    "name": "Tenant A Experiment",
                    "organization_id": "other-org",
                    "dataset_id": dataset_id,
                    "plugin_grid": PLUGIN_GRID,
                },
            )
        assert create_resp.status_code == 201, create_resp.text
        experiment_id = create_resp.json()["id"]
        assert create_resp.json()["organization_id"] == tenant_a_org_id
        assert enqueue_mock.call_args.kwargs["tenant_id"] == tenant_a_org_id

        await client.post("/api/v1/auth/logout")
        await _signup(client, "experiments-tenant-b")

        list_resp = await client.get(f"/api/v1/experiments?organization_id={tenant_a_org_id}")
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json() == []

        enqueue_b_mock = _make_enqueue_mock()
        with patch("ragp_api.api.v1.routes_experiments.enqueue", enqueue_b_mock):
            create_b_resp = await client.post(
                "/api/v1/experiments",
                json={
                    "name": "Tenant B Experiment",
                    "organization_id": tenant_a_org_id,
                    "dataset_id": dataset_id,
                    "plugin_grid": PLUGIN_GRID,
                },
            )
        assert create_b_resp.status_code == 404, create_b_resp.text
        enqueue_b_mock.assert_not_awaited()

        assert (await client.get(f"/api/v1/experiments/{experiment_id}")).status_code == 404
        assert (
            await client.get(f"/api/v1/experiments/{experiment_id}/leaderboard")
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/experiments/{experiment_id}/promote_to_pipeline",
                json={"name": "Cross Org Promote"},
            )
        ).status_code == 404
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header
