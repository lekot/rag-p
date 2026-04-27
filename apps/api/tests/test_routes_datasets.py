import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

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
async def test_upload_json_file(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    content = json.dumps({"items": [{"id": i, "text": "fact " * 30} for i in range(20)]})

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("kb.json", io.BytesIO(content.encode()), "application/json")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 201
    assert resp.json()["chunk_count"] > 0


@pytest.mark.asyncio
async def test_upload_csv_by_extension(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    rows = "\n".join(f"{i},name-{i},value-{i * 10}" for i in range(50))
    content = f"id,name,value\n{rows}\n"

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        # content-type intentionally generic — extension must drive acceptance
        files={"file": ("data.csv", io.BytesIO(content.encode()), "application/octet-stream")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 201


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


# ---------------------------------------------------------------------------
# POST /datasets/{dataset_id}/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_top_k(client: AsyncClient, organization_id: str):
    """Search endpoint returns chunks with correct shape; embedder and retriever are mocked."""
    dataset_id = await _create_dataset(client, organization_id)
    sample = "The quick brown fox jumps over the lazy dog. " * 60

    upload_resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("fox.txt", io.BytesIO(sample.encode()), "text/plain")},
        data={"chunker_name": "recursive-character"},
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document_id"]

    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": "The quick brown fox jumps",
            "score": 0.021,
            "metadata": {"chunk_index": 0},
            "document_id": doc_id,
            "document_name": "upload://fox.txt",
        },
        {
            "id": str(uuid.uuid4()),
            "text": "over the lazy dog",
            "score": 0.018,
            "metadata": {"chunk_index": 1},
            "document_id": doc_id,
            "document_name": "upload://fox.txt",
        },
    ]

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_mock_get_plugin(fake_chunks),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/search",
            headers={"X-Organization-Id": organization_id},
            json={"query": "fox", "top_k": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "chunks" in body
    assert len(body["chunks"]) == len(fake_chunks)
    for chunk in body["chunks"]:
        assert "id" in chunk
        assert "text" in chunk
        assert "score" in chunk
        assert "metadata" in chunk
        assert "document_id" in chunk
        assert "document_name" in chunk


@pytest.mark.asyncio
async def test_search_dataset_not_found_returns_404(client: AsyncClient, organization_id: str):
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/datasets/{fake_id}/search",
        headers={"X-Organization-Id": organization_id},
        json={"query": "hello", "top_k": 5},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_without_org_header_returns_422(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/search",
        json={"query": "hello", "top_k": 5},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Helper: wrap get_plugin so embedder and retriever are mocked
# ---------------------------------------------------------------------------


def _make_mock_get_plugin(fake_chunks: list[dict]):
    """Return a get_plugin side_effect that stubs embedder and retriever plugins."""

    fake_vec = [0.0] * 1024

    class _FakeEmbedder:
        def __init__(self, params):  # noqa: ANN001
            pass

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [fake_vec for _ in texts]

    class _FakeRetriever:
        def __init__(self, params):  # noqa: ANN001
            pass

        async def retrieve(self, **kwargs) -> list[dict]:  # noqa: ANN003
            return fake_chunks

    def _side_effect(plugin_type: str, name: str):  # noqa: ANN001
        if plugin_type == "embedder":
            return _FakeEmbedder
        if plugin_type == "retriever":
            return _FakeRetriever
        return None

    return _side_effect


def _make_ask_get_plugin(fake_chunks: list[dict], generator_mock: MagicMock):
    """Return a get_plugin side_effect that stubs embedder, retriever, and generator plugins."""

    fake_vec = [0.0] * 1024

    class _FakeEmbedder:
        def __init__(self, params):  # noqa: ANN001
            pass

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [fake_vec for _ in texts]

    class _FakeRetriever:
        def __init__(self, params):  # noqa: ANN001
            pass

        async def retrieve(self, **kwargs) -> list[dict]:  # noqa: ANN003
            return fake_chunks

    def _side_effect(plugin_type: str, name: str):  # noqa: ANN001
        if plugin_type == "embedder":
            return _FakeEmbedder
        if plugin_type == "retriever":
            return _FakeRetriever
        if plugin_type == "generator":
            return generator_mock
        return None

    return _side_effect


# ---------------------------------------------------------------------------
# POST /datasets/{dataset_id}/ask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_returns_answer_with_chunks(client: AsyncClient, organization_id: str):
    """Ask endpoint returns answer, chunks and usage; embedder, retriever, generator are mocked."""
    dataset_id = await _create_dataset(client, organization_id)

    doc_id = str(uuid.uuid4())
    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": "The quick brown fox jumps",
            "score": 0.021234,
            "metadata": {"chunk_index": 0},
            "document_id": doc_id,
            "document_name": "upload://fox.txt",
        },
    ]

    # Generator class mock: constructor returns an instance with async generate()
    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock(
        return_value={
            "answer": "The fox jumps.",
            "trace": {
                "model": "deepseek/deepseek-v4-flash",
                "usage": {"prompt_tokens": 42, "completion_tokens": 10},
            },
        }
    )

    generator_cls = MagicMock(return_value=gen_instance)

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_ask_get_plugin(fake_chunks, generator_cls),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "What does the fox do?", "top_k": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "The fox jumps."
    assert len(body["chunks"]) == 1
    chunk = body["chunks"][0]
    assert "id" in chunk
    assert "text" in chunk
    assert "score" in chunk
    assert "document_id" in chunk
    assert "document_name" in chunk
    # Score must be rounded to 4 decimal places
    assert chunk["score"] == round(0.021234, 4)
    assert body["usage"]["prompt_tokens"] == 42
    assert body["usage"]["completion_tokens"] == 10
    # Ensure generator was called
    gen_instance.generate.assert_called_once()


@pytest.mark.asyncio
async def test_ask_empty_retrieval_skips_llm(client: AsyncClient, organization_id: str):
    """When retriever returns empty list, LLM must NOT be called."""
    dataset_id = await _create_dataset(client, organization_id)

    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock()

    generator_cls = MagicMock(return_value=gen_instance)

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_ask_get_plugin([], generator_cls),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "anything", "top_k": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks"] == []
    assert body["usage"]["prompt_tokens"] == 0
    assert body["usage"]["completion_tokens"] == 0
    assert "answer" in body
    # LLM must not have been called
    gen_instance.generate.assert_not_called()


@pytest.mark.asyncio
async def test_ask_dataset_not_found_returns_404(client: AsyncClient, organization_id: str):
    fake_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/datasets/{fake_id}/ask",
        headers={"X-Organization-Id": organization_id},
        json={"query": "hello", "top_k": 5},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ask_pipeline_path_returns_usage(
    client: AsyncClient,
    organization_id: str,
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    """When pipeline_id is used, usage.prompt_tokens must be > 0 (token passthrough)."""
    from ragp_api.db.models import Pipeline, PipelineVersion

    dataset_id = await _create_dataset(client, organization_id)

    version_id = str(uuid.uuid4())
    pipeline_id = str(uuid.uuid4())

    nodes = [
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
        organization_id=organization_id,
        name="Test Pipeline",
        dataset_id=dataset_id,
        current_version_id=version_id,
    )
    db_session.add_all([ver, pl])
    await db_session.commit()

    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": "context text",
            "score": 0.9,
            "metadata": {},
            "document_id": str(uuid.uuid4()),
            "document_name": "doc.txt",
        }
    ]

    mock_run_result = {
        "answer": "Pipeline answer",
        "contexts": fake_chunks,
        "traces": [
            {
                "kind": "generator",
                "name": "litellm-generator",
                "trace": {"usage": {"prompt_tokens": 55, "completion_tokens": 15}},
            }
        ],
        "usage": {"prompt_tokens": 55, "completion_tokens": 15},
    }

    with patch(
        "ragp_api.api.v1.routes_datasets.run_pipeline",
        new=AsyncMock(return_value=mock_run_result),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "what?", "pipeline_id": pipeline_id},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Pipeline answer"
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["prompt_tokens"] == 55
    assert body["usage"]["completion_tokens"] == 15


# ---------------------------------------------------------------------------
# PDF / DOCX upload
# ---------------------------------------------------------------------------


def _make_minimal_pdf_with_text(text: str) -> bytes:
    """Build a minimal valid PDF containing *text* using pypdf's PdfWriter."""
    from pypdf import PdfWriter  # type: ignore[import-untyped]
    from pypdf.generic import (  # type: ignore[import-untyped]
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # Build a minimal content stream: BT ... ET
    content_stream = DecodedStreamObject()
    pdf_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content_stream.set_data(f"BT /F1 12 Tf 72 720 Td ({pdf_text}) Tj ET".encode())

    # Register font resource so the page is valid
    font_dict = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font_dict)})}
    )
    page[NameObject("/Resources")] = resources  # type: ignore[index]
    page[NameObject("/Contents")] = writer._add_object(content_stream)  # type: ignore[index]

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_empty_pdf() -> bytes:
    """Build a valid PDF with one blank page (no text content stream)."""
    from pypdf import PdfWriter  # type: ignore[import-untyped]

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_docx_with_text(text: str) -> bytes:
    """Build a minimal DOCX file with one paragraph."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_pdf_extracts_text(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    pdf_bytes = _make_minimal_pdf_with_text("Hello PDF world. " * 50)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("document.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["chunk_count"] > 0


@pytest.mark.asyncio
async def test_upload_docx_extracts_text(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    docx_bytes = _make_docx_with_text("Hello DOCX world. " * 50)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={
            "file": (
                "document.docx",
                io.BytesIO(docx_bytes),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["chunk_count"] > 0


@pytest.mark.asyncio
async def test_upload_pdf_with_no_text_returns_422(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    pdf_bytes = _make_empty_pdf()

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("blank.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        data={"chunker_name": "recursive-character"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "No text" in detail or "no extractable text" in detail.lower()
