"""Tests for experiment routes and pipeline promotion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


async def _create_dataset(client: AsyncClient, organization_id: str) -> str:
    resp = await client.post(
        "/api/v1/datasets",
        json={"name": "Test Dataset", "organization_id": organization_id},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


PLUGIN_GRID = {
    "chunkers": [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}],
    "retrievers": [{"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}}],
    "generators": [
        {
            "plugin_kind": "generator",
            "plugin_name": "litellm-generator",
            "params": {"model": "openai/gpt-4o-mini"},
        }
    ],
}


def _make_redis_pool_mock() -> MagicMock:
    """Return a mock that behaves like an arq ArqRedis pool."""
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
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        response = await client.post(
            "/api/v1/experiments",
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

    # Verify enqueue_job was called with the experiment id
    pool_mock.enqueue_job.assert_called_once_with("run_experiment_task", data["id"])


@pytest.mark.asyncio
async def test_create_experiment_enqueues_job(client: AsyncClient, organization_id: str):
    """POST /experiments enqueues 'run_experiment_task' — job id is returned."""
    dataset_id = await _create_dataset(client, organization_id)
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        response = await client.post(
            "/api/v1/experiments",
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
    pool_mock.enqueue_job.assert_awaited_once()
    call_args = pool_mock.enqueue_job.call_args
    assert call_args.args[0] == "run_experiment_task"
    assert call_args.args[1] == data["id"]


@pytest.mark.asyncio
async def test_create_experiment_redis_pool_closed_on_success(
    client: AsyncClient, organization_id: str
):
    """create_pool.aclose() must be called even when enqueue succeeds."""
    dataset_id = await _create_dataset(client, organization_id)
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        await client.post(
            "/api/v1/experiments",
            json={
                "name": "Close Test",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    pool_mock.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_experiments_org_filtered(client: AsyncClient, organization_id: str):
    """GET /experiments?organization_id=... returns only org's experiments."""
    dataset_id = await _create_dataset(client, organization_id)
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        await client.post(
            "/api/v1/experiments",
            json={
                "name": "Exp 1",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )
        await client.post(
            "/api/v1/experiments",
            json={
                "name": "Exp 2",
                "organization_id": "other-org",
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    list_resp = await client.get(f"/api/v1/experiments?organization_id={organization_id}")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert all(e["organization_id"] == organization_id for e in data)
    assert any(e["name"] == "Exp 1" for e in data)
    assert not any(e["name"] == "Exp 2" for e in data)


@pytest.mark.asyncio
async def test_get_experiment_by_id(client: AsyncClient, organization_id: str):
    """GET /experiments/{id} returns full experiment including plugin_grid."""
    dataset_id = await _create_dataset(client, organization_id)
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        create_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "Detailed Exp",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    exp_id = create_resp.json()["id"]
    resp = await client.get(f"/api/v1/experiments/{exp_id}")
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
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        create_resp = await client.post(
            "/api/v1/experiments",
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

    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        create_resp = await client.post(
            "/api/v1/experiments",
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
        json={"name": "DS1", "organization_id": organization_id},
    )
    ds1_id = ds1_resp.json()["id"]
    ds2_resp = await client.post(
        "/api/v1/datasets",
        json={"name": "DS2", "organization_id": organization_id},
    )
    ds2_id = ds2_resp.json()["id"]

    winning_nodes = [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}]
    pool_mock = _make_redis_pool_mock()

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        return_value=pool_mock,
    ):
        exp_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "DS1 Exp",
                "organization_id": organization_id,
                "dataset_id": ds1_id,
                "plugin_grid": {
                    "chunkers": [
                        {
                            "plugin_kind": "chunker",
                            "plugin_name": "recursive-character",
                            "params": {},
                        }
                    ]
                },
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
        json={"name": "Pipeline for DS1"},
    )

    # Get pipelines filtered by ds1
    list_resp = await client.get(
        f"/api/v1/pipelines?organization_id={organization_id}&dataset_id={ds1_id}"
    )
    assert list_resp.status_code == 200
    pipelines = list_resp.json()
    assert len(pipelines) >= 1
    assert all(p["dataset_id"] == ds1_id for p in pipelines)

    # ds2 should return empty
    list_resp2 = await client.get(
        f"/api/v1/pipelines?organization_id={organization_id}&dataset_id={ds2_id}"
    )
    assert list_resp2.status_code == 200
    assert list_resp2.json() == []
