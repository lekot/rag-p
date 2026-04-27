"""Tests for experiment routes and pipeline promotion."""

from unittest.mock import patch

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


@pytest.mark.asyncio
async def test_create_experiment_completes(client: AsyncClient, organization_id: str):
    """POST /experiments should create experiment and transition to completed or failed."""
    dataset_id = await _create_dataset(client, organization_id)

    # Mock inline runner so it doesn't do real DB retrieval
    async def mock_runner(experiment, db):
        experiment.status = "completed"
        experiment.leaderboard_json = [
            {
                "nodes": [
                    {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}
                ],
                "metrics": {"hit_rate": 0.8, "composite_score": 0.8},
                "composite_score": 0.8,
            }
        ]
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner,
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
    assert data["id"]
    assert data["name"] == "Test Experiment"
    assert data["dataset_id"] == dataset_id
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_create_experiment_failed(client: AsyncClient, organization_id: str):
    """When runner fails, experiment status should be 'failed'."""
    dataset_id = await _create_dataset(client, organization_id)

    async def mock_runner_fail(experiment, db):
        experiment.status = "failed"
        experiment.leaderboard_json = [{"error": "LLM key invalid"}]
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner_fail,
    ):
        response = await client.post(
            "/api/v1/experiments",
            json={
                "name": "Failed Experiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "failed"


@pytest.mark.asyncio
async def test_list_experiments_org_filtered(client: AsyncClient, organization_id: str):
    """GET /experiments?organization_id=... returns only org's experiments."""
    dataset_id = await _create_dataset(client, organization_id)

    async def mock_runner_complete(experiment, db):
        experiment.status = "completed"
        experiment.leaderboard_json = []
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner_complete,
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
    """GET /experiments/{id} returns full experiment including plugin_grid and leaderboard."""
    dataset_id = await _create_dataset(client, organization_id)

    async def mock_runner(experiment, db):
        experiment.status = "completed"
        experiment.leaderboard_json = [
            {"nodes": [], "metrics": {"composite_score": 0.7}, "composite_score": 0.7}
        ]
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner,
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
    assert data["leaderboard"] is not None


@pytest.mark.asyncio
async def test_promote_to_pipeline(client: AsyncClient, organization_id: str):
    """POST /experiments/{id}/promote_to_pipeline creates pipeline with dataset_id."""
    dataset_id = await _create_dataset(client, organization_id)

    winning_nodes = [
        {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}},
        {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}},
    ]

    async def mock_runner(experiment, db):
        experiment.status = "completed"
        experiment.leaderboard_json = [
            {"nodes": winning_nodes, "metrics": {"composite_score": 0.9}, "composite_score": 0.9}
        ]
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner,
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
async def test_pipeline_list_filter_by_dataset(client: AsyncClient, organization_id: str):
    """GET /pipelines?dataset_id=... filters by dataset."""
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

    # Create pipeline linked to ds1
    winning_nodes = [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}]

    async def mock_runner_ds1(experiment, db):
        experiment.status = "completed"
        experiment.leaderboard_json = [
            {"nodes": winning_nodes, "metrics": {"composite_score": 0.9}, "composite_score": 0.9}
        ]
        await db.commit()

    with patch(
        "ragp_api.api.v1.routes_experiments.run_experiment_inline",
        side_effect=mock_runner_ds1,
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
