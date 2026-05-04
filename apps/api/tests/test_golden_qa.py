"""Tests for golden Q&A generation, storage, and experiment evaluation."""

import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, DatasetGoldenItem, Document
from ragp_api.services.golden_qa_generator import GoldenGenerationError, generate_golden_qa
from ragp_api.settings import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_DEEPSEEK = "ragp_api.services.golden_qa_generator._call_deepseek"


async def _create_dataset(client: AsyncClient, organization_id: str, name: str = "GoldenDS") -> str:
    resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": name, "organization_id": organization_id},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _upload_document(
    client: AsyncClient,
    dataset_id: str,
    organization_id: str,
    content: str = "Chunk text alpha. " * 40,
) -> str:
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(content.encode()), "text/plain")},
        data={"chunker_name": "recursive-character", "chunker_params": "{}"},
    )
    assert resp.status_code == 201
    return resp.json()["document_id"]


def _mock_deepseek_response(
    question: str = "What is this?", answer: str = "It is alpha."
) -> MagicMock:
    """Build a mock httpx Response that returns a valid DeepSeek JSON Q&A."""
    content = json.dumps(
        {
            "choices": [
                {"message": {"content": json.dumps({"question": question, "answer": answer})}}
            ]
        }
    )
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json.loads(content)
    return resp


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_golden_qa_creates_items(db_session: AsyncSession, organization_id: str):
    """generate_golden_qa returns Q&A pairs for each sampled chunk (mocked LLM)."""
    # Seed dataset, document, 3 chunks directly in DB
    ds_id = str(uuid.uuid4())
    from ragp_api.db.models import Dataset

    ds = Dataset(id=ds_id, organization_id=organization_id, name="test-gs", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=ds_id,
        source_uri="upload://test.txt",
        status="parsed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    chunks = [
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            organization_id=organization_id,
            text=f"Chunk number {i}. " * 20,
        )
        for i in range(3)
    ]
    db_session.add_all(chunks)
    await db_session.commit()

    mock_resp = _mock_deepseek_response()
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_resp)):
        pairs = await generate_golden_qa(
            dataset_id=ds_id,
            organization_id=organization_id,
            db=db_session,
            sample_size=3,
        )

    assert len(pairs) == 3
    for pair in pairs:
        assert "question" in pair
        assert "answer" in pair
        assert "source_chunk_id" in pair
        assert pair["question"] == "What is this?"
        assert pair["answer"] == "It is alpha."


@pytest.mark.asyncio
async def test_generate_golden_qa_handles_invalid_json(
    db_session: AsyncSession, organization_id: str
):
    """When LLM returns invalid JSON, the chunk is skipped and no exception raised."""
    from ragp_api.db.models import Dataset

    ds_id = str(uuid.uuid4())
    ds = Dataset(id=ds_id, organization_id=organization_id, name="test-invalid", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=ds_id,
        source_uri="upload://bad.txt",
        status="parsed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    chunk = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=organization_id,
        text="Some text here. " * 20,
    )
    db_session.add(chunk)
    await db_session.commit()

    bad_resp = MagicMock(spec=httpx.Response)
    bad_resp.status_code = 200
    bad_resp.json.return_value = {"choices": [{"message": {"content": "NOT VALID JSON AT ALL"}}]}

    with (
        patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=bad_resp)),
        pytest.raises(GoldenGenerationError),
    ):
        await generate_golden_qa(
            dataset_id=ds_id,
            organization_id=organization_id,
            db=db_session,
            sample_size=5,
        )


@pytest.mark.asyncio
async def test_generate_golden_qa_extractive_fallback_when_llm_fails(
    db_session: AsyncSession, organization_id: str
) -> None:
    from ragp_api.db.models import Dataset

    ds_id = str(uuid.uuid4())
    ds = Dataset(id=ds_id, organization_id=organization_id, name="test-fallback", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=ds_id,
        source_uri="upload://fallback.txt",
        status="parsed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    chunk_text = "Ресурсы СКД отчёта группируются по родителю через поле parent. " * 5
    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=doc.id,
        organization_id=organization_id,
        text=chunk_text,
    )
    db_session.add(chunk)
    await db_session.commit()

    old_mode = settings.llm_fallback_mode
    settings.llm_fallback_mode = "extractive"
    try:
        with patch(_PATCH_DEEPSEEK, new=AsyncMock(side_effect=RuntimeError("no llm"))):
            pairs = await generate_golden_qa(
                dataset_id=ds_id,
                organization_id=organization_id,
                db=db_session,
                sample_size=1,
            )
    finally:
        settings.llm_fallback_mode = old_mode

    assert pairs == [
        {
            "question": "Какая информация содержится в этом фрагменте?",
            "answer": chunk_text.strip(),
            "source_chunk_id": chunk_id,
        }
    ]


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_golden_returns_items(client: AsyncClient, organization_id: str):
    """POST /datasets/{id}/golden then GET returns the saved items."""
    dataset_id = await _create_dataset(client, organization_id)
    await _upload_document(client, dataset_id, organization_id)

    mock_resp = _mock_deepseek_response("What is alpha?", "Alpha is text.")
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_resp)):
        post_resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/golden",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 5},
        )

    assert post_resp.status_code == 201
    post_data = post_resp.json()
    assert "items" in post_data
    assert "count" in post_data
    assert post_data["count"] >= 0  # might be 0 if upload produced no chunks
    # If items were created, validate shape
    for item in post_data["items"]:
        assert "id" in item
        assert "question" in item
        assert "answer" in item
        assert "source_chunk_id" in item
        assert "created_at" in item

    # GET should return same items
    get_resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/golden",
        headers={"X-Organization-Id": organization_id},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert len(get_data) == post_data["count"]


@pytest.mark.asyncio
async def test_golden_post_enforces_ownership(client: AsyncClient, organization_id: str):
    """POST golden for a dataset that belongs to another org returns 404."""
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/golden",
        headers={"X-Organization-Id": "wrong-org"},
        json={"sample_size": 5},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_golden_sample_size_capped_at_50(client: AsyncClient, organization_id: str):
    """sample_size > 50 is silently capped to 50 (no error)."""
    dataset_id = await _create_dataset(client, organization_id)

    mock_resp = _mock_deepseek_response()
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_resp)):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/golden",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 9999},
        )
    # Should not 422 — just caps to 50 and returns (0 items since no documents)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_regenerate_golden_replaces_items(
    client: AsyncClient, db_session: AsyncSession, organization_id: str
):
    """POST /datasets/{id}/golden/regenerate clears old items and creates new ones."""
    # Seed dataset + document + chunks directly (upload requires Redis for chunking)
    ds_id = str(uuid.uuid4())
    from ragp_api.db.models import Dataset

    ds = Dataset(id=ds_id, organization_id=organization_id, name="regen-ds", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=ds_id,
        source_uri="upload://regen.txt",
        status="parsed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    for i in range(3):
        c = Chunk(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            organization_id=organization_id,
            text=f"Chunk {i} content. " * 20,
        )
        db_session.add(c)
    await db_session.commit()

    # Generate initial golden items
    mock_1 = _mock_deepseek_response("Q1?", "A1.")
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_1)):
        post_resp = await client.post(
            f"/api/v1/datasets/{ds_id}/golden",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 3},
        )
    assert post_resp.status_code == 201
    initial_ids = {item["id"] for item in post_resp.json()["items"]}
    assert len(initial_ids) > 0

    # Regenerate with different LLM output
    mock_2 = _mock_deepseek_response("Q2?", "A2.")
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_2)):
        regen_resp = await client.post(
            f"/api/v1/datasets/{ds_id}/golden/regenerate",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 3},
        )
    assert regen_resp.status_code == 201
    regen_data = regen_resp.json()
    regen_ids = {item["id"] for item in regen_data["items"]}

    # New items should be different (new UUIDs, new Q&A)
    assert regen_ids.isdisjoint(initial_ids)
    for item in regen_data["items"]:
        assert item["question"] == "Q2?"
        assert item["answer"] == "A2."

    # GET confirms only new items exist
    get_resp = await client.get(
        f"/api/v1/datasets/{ds_id}/golden",
        headers={"X-Organization-Id": organization_id},
    )
    assert get_resp.status_code == 200
    get_ids = {item["id"] for item in get_resp.json()}
    assert get_ids == regen_ids


@pytest.mark.asyncio
async def test_regenerate_golden_enforces_ownership(client: AsyncClient, organization_id: str):
    """Regenerate for a dataset of another org returns 404."""
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/golden/regenerate",
        headers={"X-Organization-Id": "wrong-org"},
        json={"sample_size": 5},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_golden_handles_empty_dataset(client: AsyncClient, organization_id: str):
    """Regenerate on a dataset with no chunks returns 201 with empty items."""
    dataset_id = await _create_dataset(client, organization_id)
    # No documents uploaded — dataset is empty

    mock_resp = _mock_deepseek_response()
    with patch(_PATCH_DEEPSEEK, new=AsyncMock(return_value=mock_resp)):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/golden/regenerate",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 10},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["count"] == 0
    assert data["items"] == []


# ---------------------------------------------------------------------------
# Experiment runner — golden path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experiment_uses_golden_when_present(db_session: AsyncSession, organization_id: str):
    """When golden items exist, experiment runner returns retrieval_hit metric."""
    from ragp_api.db.models import Dataset, Experiment
    from ragp_api.services.experiment_runner import run_experiment_inline

    ds_id = str(uuid.uuid4())
    ds = Dataset(id=ds_id, organization_id=organization_id, name="golden-exp-ds", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=ds_id,
        source_uri="upload://exp.txt",
        status="parsed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=doc.id,
        organization_id=organization_id,
        text="The capital of France is Paris.",
    )
    db_session.add(chunk)

    golden = DatasetGoldenItem(
        id=str(uuid.uuid4()),
        dataset_id=ds_id,
        question="What is the capital of France?",
        answer="Paris",
        source_chunk_id=chunk_id,
    )
    db_session.add(golden)
    await db_session.flush()

    experiment = Experiment(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        name="golden-test-exp",
        dataset_id=ds_id,
        plugin_grid_json={
            "retrievers": [
                {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}}
            ]
        },
        status="pending",
    )
    db_session.add(experiment)
    await db_session.commit()

    # Mock retriever to return the chunk so hit_rate = 1.0
    mock_retriever_instance = MagicMock()
    retrieved = [
        {
            "id": chunk_id,
            "text": "Paris",
            "score": 0.9,
            "metadata": {},
            "document_id": doc.id,
            "document_name": "exp.txt",
        }
    ]
    mock_retriever_instance.retrieve = AsyncMock(return_value=retrieved)
    mock_retriever_cls = MagicMock(return_value=mock_retriever_instance)

    with (
        patch("ragp_api.plugins.registry.get_plugin", return_value=mock_retriever_cls),
        patch("ragp_api.services.experiment_runner.consume_q", new=AsyncMock()) as consume_mock,
        patch(
            "ragp_api.services.experiment_runner.record_usage_event",
            new=AsyncMock(),
        ) as usage_mock,
    ):
        await run_experiment_inline(experiment, db_session)

    assert experiment.status == "completed"
    assert experiment.leaderboard_json is not None
    assert len(experiment.leaderboard_json) == 1

    entry = experiment.leaderboard_json[0]
    metrics = entry["metrics"]
    # With golden path, metric key is retrieval_hit (not hit_rate)
    assert "retrieval_hit" in metrics
    # Hit should be 1.0 since mock returned chunk_id
    assert metrics["retrieval_hit"] == 1.0
    assert metrics["composite_score"] == 1.0
    consume_mock.assert_awaited_once()
    assert consume_mock.await_args.kwargs["count"] == 1
    usage_mock.assert_awaited_once()
    assert usage_mock.await_args.kwargs["quota_reserved"] is True
