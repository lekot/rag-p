import io
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Dataset, Document, Chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_dataset(client: AsyncClient, organization_id: str, name: str = "Test DS") -> str:
    resp = await client.post(
        "/api/v1/datasets",
        json={"name": name, "organization_id": organization_id, "source": "uploaded"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _txt_upload(content: str, filename: str = "hello.txt") -> dict:
    return {
        "file": (filename, io.BytesIO(content.encode()), "text/plain"),
    }


# ---------------------------------------------------------------------------
# POST /datasets/{dataset_id}/documents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_txt_creates_chunks(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    sample = "Hello world. " * 200  # ~2600 chars — enough for multiple chunks

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(sample.encode()), "text/plain")},
        data={"chunker_name": "recursive-character", "chunker_params": "{}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["document_id"]
    assert body["chunk_count"] > 0
    assert isinstance(body["chunks_preview"], list)
    assert len(body["chunks_preview"]) <= 5
    assert body["chunks_preview"][0]["len"] > 0
    # No OPENAI_API_KEY in test env → embedded must be False
    assert body["embedded"] is False


@pytest.mark.asyncio
async def test_upload_md_file(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    content = "# Title\n\nSome paragraph.\n\n## Section\n\nMore text here. " * 20

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("readme.md", io.BytesIO(content.encode()), "text/markdown")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 201
    assert resp.json()["chunk_count"] > 0


@pytest.mark.asyncio
async def test_upload_unsupported_type_returns_415(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("archive.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_upload_without_org_header_returns_422(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)

    # No X-Organization-Id header → FastAPI returns 422 (missing required header)
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_invalid_chunker_params_returns_422(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"chunker_name": "recursive-character", "chunker_params": '{"chunk_size": 5}'},
    )
    # chunk_size minimum is 64 — jsonschema validation must reject 5
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_unknown_chunker_returns_422(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"chunker_name": "nonexistent-chunker"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_dataset_not_found_returns_404(client: AsyncClient, organization_id: str):
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/datasets/{fake_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /datasets/{dataset_id}/documents/{document_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_document_returns_chunks(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    sample = "Chunk content. " * 100

    upload_resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("test.txt", io.BytesIO(sample.encode()), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document_id"]
    expected_count = upload_resp.json()["chunk_count"]

    get_resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{doc_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == doc_id
    assert body["status"] == "parsed"
    assert body["chunk_count"] == expected_count
    assert len(body["chunks"]) == expected_count
    for chunk in body["chunks"]:
        assert "text" in chunk
        assert "len" in chunk
        assert "has_embedding" in chunk
        assert chunk["has_embedding"] is False  # no key in test env


@pytest.mark.asyncio
async def test_get_document_not_found(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{uuid.uuid4()}",
        headers={"X-Organization-Id": organization_id},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /datasets/{dataset_id}/documents (list)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_documents_after_upload(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    sample = "Some text. " * 50

    await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("a.txt", io.BytesIO(sample.encode()), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )
    await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("b.txt", io.BytesIO(sample.encode()), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )

    resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
    )
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) == 2
    for doc in docs:
        assert doc["chunk_count"] > 0
        assert doc["status"] == "parsed"
