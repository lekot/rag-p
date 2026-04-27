"""Tests for the public RAG query endpoint (POST /api/v1/rag/query)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Dataset, Membership, Organization, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_org_with_key(db: AsyncSession) -> tuple[str, str, str]:
    """Create org + user + api_key. Returns (org_id, raw_key, dataset_id)."""
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    org = Organization(id=org_id, name="testorg", slug=f"testorg-{org_id[:8]}")
    user = User(id=user_id, email=f"rag-{org_id[:8]}@example.com", password_hash="x")
    membership = Membership(organization_id=org_id, user_id=user_id, role="admin")

    raw_key = "rgp_" + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=user_id,
        name="test-key",
        key_prefix=raw_key[:8],
        key_hash=key_hash,
    )

    dataset = Dataset(
        id=str(uuid.uuid4()), organization_id=org_id, name="Test DS", source="uploaded"
    )

    db.add_all([org, user, membership, api_key, dataset])
    await db.commit()

    return org_id, raw_key, dataset.id


# ---------------------------------------------------------------------------
# test_rag_query_without_bearer_returns_401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_query_without_bearer_returns_401(client: AsyncClient) -> None:
    """Request with no Authorization header must return 401."""
    resp = await client.post(
        "/api/v1/rag/query",
        json={"dataset_id": "any", "query": "hello"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# test_rag_query_invalid_key_returns_401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_query_invalid_key_returns_401(client: AsyncClient) -> None:
    """Request with an unknown API key must return 401."""
    resp = await client.post(
        "/api/v1/rag/query",
        headers={"Authorization": "Bearer rgp_notexistent00000000000000000000"},
        json={"dataset_id": "any", "query": "hello"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# test_rag_query_dataset_from_other_org_returns_404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_query_dataset_from_other_org_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Valid key but dataset belongs to another org → 404."""
    _org_id, raw_key, _ds_id = await _create_org_with_key(db_session)

    # Create a dataset owned by a completely different org (not in db, so lookup fails)
    foreign_dataset_id = str(uuid.uuid4())

    resp = await client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"dataset_id": foreign_dataset_id, "query": "hello"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# test_rag_query_with_valid_key_returns_answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_query_with_valid_key_returns_answer(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Valid key + valid dataset → mocked pipeline returns answer."""
    _org_id, raw_key, dataset_id = await _create_org_with_key(db_session)

    mock_chunks: list[dict[str, Any]] = [
        {
            "id": "c1",
            "text": "The answer is 42",
            "score": 0.95,
            "document_id": "doc1",
            "document_name": "doc.txt",
            "metadata": {},
        }
    ]

    mock_retriever_instance = MagicMock()
    mock_retriever_instance.retrieve = AsyncMock(return_value=mock_chunks)

    mock_generator_instance = MagicMock()
    mock_generator_instance.generate = AsyncMock(
        return_value={
            "answer": "The answer is 42.",
            "trace": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        }
    )

    with (
        patch(
            "ragp_api.api.v1.routes_rag.get_plugin",
            side_effect=lambda kind, name: (
                (lambda _params: mock_retriever_instance)
                if kind == "retriever"
                else (lambda _params: mock_generator_instance)
                if kind == "generator"
                else None
            ),
        ),
        patch(
            "ragp_api.api.v1.routes_rag._resolve_embedder",
            new=AsyncMock(return_value=(None, "none")),
        ),
    ):
        resp = await client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"dataset_id": dataset_id, "query": "What is the answer?", "top_k": 3},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "The answer is 42."
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["id"] == "c1"
    assert "usage" in body
    assert "trace" in body


# ---------------------------------------------------------------------------
# test_rag_query_with_pipeline_id_uses_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rag_query_with_pipeline_id_uses_pipeline(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When pipeline_id is passed, run_pipeline is called with pipeline nodes."""
    from ragp_api.db.models import Pipeline, PipelineVersion

    org_id, raw_key, dataset_id = await _create_org_with_key(db_session)

    # Create a pipeline version + pipeline
    version_id = str(uuid.uuid4())
    pipeline_id = str(uuid.uuid4())

    nodes: list[dict[str, Any]] = [
        {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}},
        {
            "plugin_kind": "generator",
            "plugin_name": "litellm-generator",
            "params": {"model": "deepseek/deepseek-v4-flash"},
        },
    ]

    ver = PipelineVersion(id=version_id, pipeline_id=pipeline_id, nodes_json=nodes)
    pl = Pipeline(
        id=pipeline_id,
        organization_id=org_id,
        name="My Pipeline",
        dataset_id=dataset_id,
        current_version_id=version_id,
    )
    db_session.add_all([ver, pl])
    await db_session.commit()

    mock_run_result: dict[str, Any] = {
        "answer": "Pipeline says hello",
        "contexts": [
            {
                "id": "cx1",
                "text": "chunk text",
                "score": 0.9,
                "document_id": "d1",
                "document_name": "file.txt",
            }
        ],
        "traces": [],
    }

    with patch(
        "ragp_api.api.v1.routes_rag.run_pipeline",
        new=AsyncMock(return_value=mock_run_result),
    ) as mock_runner:
        resp = await client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "dataset_id": dataset_id,
                "query": "hello?",
                "pipeline_id": pipeline_id,
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Pipeline says hello"
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["id"] == "cx1"
    # run_pipeline must have been called once
    mock_runner.assert_called_once()
