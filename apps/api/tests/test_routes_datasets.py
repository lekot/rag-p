import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from ragp_api.db.models import (
    Chunk,
    Dataset,
    DatasetGoldenItem,
    DatasetItem,
    Document,
    Experiment,
    OrgSubscription,
    Pipeline,
    PipelineVersion,
    Plan,
    Run,
)
from ragp_api.services.object_storage import ObjectStorageRef
from ragp_api.settings import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset(client: AsyncClient, organization_id: str, name: str = "Test DS") -> str:
    resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": organization_id},
        json={"name": name, "organization_id": organization_id, "source": "uploaded"},
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


async def _grant_test_subscription(
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
    *,
    plan_id: str = "query-test",
    included_q: int = 100,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Plan(
            id=plan_id,
            name="Query Test",
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


def _txt_upload(content: str, filename: str = "hello.txt") -> dict:
    return {
        "file": (filename, io.BytesIO(content.encode()), "text/plain"),
    }


@pytest.fixture(autouse=True)
def _stub_document_enqueue(monkeypatch) -> None:
    class _Pool:
        async def enqueue_job(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return object()

        async def aclose(self) -> None:
            return None

    async def _create_pool(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return _Pool()

    import arq

    monkeypatch.setattr(arq, "create_pool", _create_pool)


@pytest.mark.asyncio
async def test_dataset_routes_scope_to_session_org_not_client_supplied_org(
    client: AsyncClient,
) -> None:
    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        tenant_a = await _signup(client, "tenant-a")
        tenant_a_org_id = tenant_a["organization"]["id"]
        create_a = await client.post(
            "/api/v1/datasets",
            headers={"X-Organization-Id": "other-org"},
            json={"name": "Tenant A DS", "organization_id": "other-org"},
        )
        assert create_a.status_code == 201, create_a.text
        tenant_a_dataset_id = create_a.json()["id"]
        assert create_a.json()["organization_id"] == tenant_a_org_id

        await client.post("/api/v1/auth/logout")

        tenant_b = await _signup(client, "tenant-b")
        tenant_b_org_id = tenant_b["organization"]["id"]
        list_b = await client.get(
            f"/api/v1/datasets?organization_id={tenant_a_org_id}",
            headers={"X-Organization-Id": tenant_a_org_id},
        )
        assert list_b.status_code == 200, list_b.text
        assert list_b.json() == []

        create_b = await client.post(
            "/api/v1/datasets",
            headers={"X-Organization-Id": tenant_a_org_id},
            json={"name": "Tenant B DS", "organization_id": tenant_a_org_id},
        )
        assert create_b.status_code == 201, create_b.text
        assert create_b.json()["organization_id"] == tenant_b_org_id

        get_a_as_b = await client.get(
            f"/api/v1/datasets/{tenant_a_dataset_id}",
            headers={"X-Organization-Id": tenant_a_org_id},
        )
        assert get_a_as_b.status_code == 404
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header


@pytest.mark.asyncio
async def test_create_dataset_requires_active_plan_when_quotas_enforced(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        resp = await client.post(
            "/api/v1/datasets",
            headers={"X-Organization-Id": organization_id},
            json={"name": "No Plan DS", "organization_id": organization_id},
        )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["code"] == "no_active_plan"
    dataset = (
        await db_session.execute(select(Dataset).where(Dataset.name == "No Plan DS"))
    ).scalar_one_or_none()
    assert dataset is None


# ---------------------------------------------------------------------------
# POST /datasets/{dataset_id}/documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_txt_creates_document(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    sample = "Hello world. " * 200

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(sample.encode()), "text/plain")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["document_id"]
    assert body["status"] == "pending"
    # Chunking is async now — no chunk_count or chunks_preview in the response


@pytest.mark.asyncio
async def test_upload_and_delete_use_raw_document_bytes_for_storage_quota(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    now = datetime.now(UTC)
    db_session.add(
        Plan(
            id="storage-test",
            name="Storage Test",
            price_rub_monthly=Decimal("100"),
            included_q=100,
            included_storage_bytes=10_000,
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
            plan_id="storage-test",
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

    dataset_id = await _create_dataset(client, organization_id)
    raw = b"a" * 700
    old_enforce_subscription_quotas = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        upload_resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            headers={"X-Organization-Id": organization_id},
            files={"file": ("doc.txt", io.BytesIO(raw), "text/plain")},
            data={
                "chunker_name": "recursive-character",
                "chunker_params": '{"chunk_size": 512, "chunk_overlap": 64}',
            },
        )
        assert upload_resp.status_code == 201, upload_resp.text

        db_session.expire_all()
        subscription = (
            await db_session.execute(
                select(OrgSubscription).where(OrgSubscription.org_id == organization_id)
            )
        ).scalar_one()
        assert subscription.storage_bytes_used == len(raw)

        document = (
            await db_session.execute(
                select(Document).where(Document.id == upload_resp.json()["document_id"])
            )
        ).scalar_one()
        assert document.raw_size_bytes == len(raw)
        assert document.content_type == "text/plain"
        assert document.sha256 is not None

        delete_resp = await client.delete(
            f"/api/v1/datasets/{dataset_id}",
            headers={"X-Organization-Id": organization_id},
        )
        assert delete_resp.status_code == 204, delete_resp.text

        db_session.expire_all()
        subscription = (
            await db_session.execute(
                select(OrgSubscription).where(OrgSubscription.org_id == organization_id)
            )
        ).scalar_one()
        assert subscription.storage_bytes_used == 0
    finally:
        settings.enforce_subscription_quotas = old_enforce_subscription_quotas


@pytest.mark.asyncio
async def test_upload_stores_raw_document_in_s3_when_configured(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    raw = b"S3 backed document. " * 50

    with patch(
        "ragp_api.api.v1.routes_datasets.store_raw_document",
        new=AsyncMock(return_value=ObjectStorageRef(backend="s3", key="orgs/o/doc.txt")),
    ) as store_mock:
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            headers={"X-Organization-Id": organization_id},
            files={"file": ("doc.txt", io.BytesIO(raw), "text/plain")},
            data={
                "chunker_name": "recursive-character",
                "chunker_params": '{"chunk_size": 512, "chunk_overlap": 64}',
            },
        )

    assert resp.status_code == 201, resp.text
    store_mock.assert_awaited_once()
    _, kwargs = store_mock.call_args
    assert kwargs["raw"] == raw
    assert kwargs["organization_id"] == organization_id
    assert kwargs["dataset_id"] == dataset_id
    assert kwargs["filename"] == "doc.txt"
    assert kwargs["content_type"] == "text/plain"

    document = (
        await db_session.execute(select(Document).where(Document.id == resp.json()["document_id"]))
    ).scalar_one()
    assert document.storage_backend == "s3"
    assert document.object_key == "orgs/o/doc.txt"


@pytest.mark.asyncio
async def test_delete_dataset_deletes_s3_raw_documents(
    client: AsyncClient,
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)

    with patch(
        "ragp_api.api.v1.routes_datasets.store_raw_document",
        new=AsyncMock(return_value=ObjectStorageRef(backend="s3", key="orgs/o/doc.txt")),
    ):
        upload_resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            headers={"X-Organization-Id": organization_id},
            files={"file": ("doc.txt", io.BytesIO(b"delete me " * 100), "text/plain")},
            data={
                "chunker_name": "recursive-character",
                "chunker_params": '{"chunk_size": 512, "chunk_overlap": 64}',
            },
        )
    assert upload_resp.status_code == 201, upload_resp.text

    with patch(
        "ragp_api.api.v1.routes_datasets.delete_raw_documents",
        new=AsyncMock(),
    ) as delete_mock:
        delete_resp = await client.delete(
            f"/api/v1/datasets/{dataset_id}",
            headers={"X-Organization-Id": organization_id},
        )

    assert delete_resp.status_code == 204, delete_resp.text
    delete_mock.assert_awaited_once()
    refs = delete_mock.call_args.args[0]
    assert refs == [ObjectStorageRef(backend="s3", key="orgs/o/doc.txt")]


@pytest.mark.asyncio
async def test_delete_dataset_cleans_runtime_dependents(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)

    upload_resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("doc.txt", io.BytesIO(b"delete runtime refs " * 100), "text/plain")},
        data={
            "chunker_name": "recursive-character",
            "chunker_params": '{"chunk_size": 512, "chunk_overlap": 64}',
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    document_id = upload_resp.json()["document_id"]

    # Chunking is async — manually create a chunk for the document
    chunk_id = str(uuid.uuid4())
    chunk = Chunk(
        id=chunk_id,
        document_id=document_id,
        organization_id=organization_id,
        text="delete runtime refs chunk",
        embedding=None,
        metadata_json={"chunk_index": 0},
    )
    db_session.add(chunk)
    await db_session.commit()
    await db_session.refresh(chunk)

    pipeline = Pipeline(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        name="Runtime pipeline",
        dataset_id=dataset_id,
    )
    pipeline_id = pipeline.id
    version = PipelineVersion(
        id=str(uuid.uuid4()),
        pipeline_id=pipeline.id,
        nodes_json=[],
    )
    db_session.add_all([pipeline, version])
    await db_session.flush()

    run = Run(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        pipeline_version_id=version.id,
        dataset_id=dataset_id,
        status="completed",
    )
    run_id = run.id
    db_session.add_all(
        [
            DatasetItem(
                id=str(uuid.uuid4()),
                dataset_id=dataset_id,
                question="q",
                golden_answer="a",
                golden_contexts_json=[],
            ),
            DatasetGoldenItem(
                id=str(uuid.uuid4()),
                dataset_id=dataset_id,
                question="golden q",
                answer="golden a",
            ),
            Experiment(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                name="Dataset experiment",
                dataset_id=dataset_id,
                plugin_grid_json={},
                status="completed",
            ),
            run,
        ]
    )
    await db_session.commit()

    delete_resp = await client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers={"X-Organization-Id": organization_id},
    )

    assert delete_resp.status_code == 204, delete_resp.text
    db_session.expire_all()
    assert (
        await db_session.execute(select(Dataset).where(Dataset.id == dataset_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Chunk).where(Chunk.id == chunk_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(DatasetItem).where(DatasetItem.dataset_id == dataset_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(
            select(DatasetGoldenItem).where(DatasetGoldenItem.dataset_id == dataset_id)
        )
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Experiment).where(Experiment.dataset_id == dataset_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    ).scalar_one().dataset_id is None
    assert (
        await db_session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one().dataset_id is None


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
    assert resp.json()["document_id"]
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_upload_json_file(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    content = json.dumps({"items": [{"id": i, "text": "fact " * 30} for i in range(20)]})

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("kb.json", io.BytesIO(content.encode()), "application/json")},
    )
    assert resp.status_code == 201
    assert resp.json()["document_id"]
    assert resp.json()["status"] == "pending"


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
async def test_upload_without_auth_returns_401(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)

    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"chunker_name": "recursive-character"},
        )
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_refuses_non_pdf_on_content_type(client: AsyncClient, organization_id: str):
    """Upload with unsupported content-type returns 415."""
    dataset_id = await _create_dataset(client, organization_id)

    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": organization_id},
        files={"file": ("foo.xyz", io.BytesIO(b"hello"), "application/x-unknown")},
    )
    assert resp.status_code == 415


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


@pytest.mark.asyncio
async def test_upload_returns_503_and_no_pending_document_when_enqueue_fails(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)

    with patch("arq.create_pool", new=AsyncMock(side_effect=RuntimeError("redis down"))):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            headers={"X-Organization-Id": organization_id},
            files={"file": ("doc.txt", io.BytesIO(b"queued failure " * 100), "text/plain")},
        )

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "document_enqueue_failed"
    db_session.expire_all()
    documents = (
        (
            await db_session.execute(
                select(Document).where(
                    Document.dataset_id == dataset_id,
                    Document.organization_id == organization_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert documents == []


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

    get_resp = await client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{doc_id}",
        headers={"X-Organization-Id": organization_id},
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == doc_id
    # Chunking is async — document exists but has no chunks yet
    assert body["status"] == "pending"
    assert body["chunk_count"] == 0
    assert body["chunks"] == []


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
        # Chunking is async — chunk_count is 0 initially
        assert doc["status"] == "pending"


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
async def test_search_without_auth_returns_401(client: AsyncClient, organization_id: str):
    dataset_id = await _create_dataset(client, organization_id)
    old_allow_legacy_org_header = settings.allow_legacy_org_header
    settings.allow_legacy_org_header = False
    try:
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/search",
            json={"query": "hello", "top_k": 5},
        )
    finally:
        settings.allow_legacy_org_header = old_allow_legacy_org_header
    assert resp.status_code == 401


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


def _make_ask_get_plugin(
    fake_chunks: list[dict],
    generator_mock: MagicMock,
    retriever_mock: AsyncMock | None = None,
):
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
            if retriever_mock is not None:
                return await retriever_mock(**kwargs)
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


def _mock_pipeline_result() -> dict:
    return {
        "answer": "Pipeline answer",
        "contexts": [],
        "traces": [],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


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
async def test_ask_default_path_expands_generation_contexts_and_tokens(
    client: AsyncClient, organization_id: str
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    doc_id = str(uuid.uuid4())
    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": f"Context {idx}",
            "score": 0.9 - (idx * 0.01),
            "metadata": {"chunk_index": idx},
            "document_id": doc_id,
            "document_name": "upload://expanded.pdf",
        }
        for idx in range(30)
    ]
    retriever_mock = AsyncMock(return_value=fake_chunks)
    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock(
        return_value={
            "answer": "Expanded answer",
            "trace": {"usage": {"prompt_tokens": 100, "completion_tokens": 20}},
        }
    )
    generator_cls = MagicMock(return_value=gen_instance)

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_ask_get_plugin(fake_chunks, generator_cls, retriever_mock),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "Show the guarantor table", "top_k": 5},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Expanded answer"
    assert len(body["chunks"]) == 30
    assert retriever_mock.await_args.kwargs["top_k"] == 30
    gen_instance.generate.assert_awaited_once()
    assert len(gen_instance.generate.await_args.kwargs["contexts"]) == 30
    assert generator_cls.call_args.args[0]["max_tokens"] >= 4096


@pytest.mark.asyncio
async def test_ask_default_path_retries_once_when_generator_reports_absent_answer(
    client: AsyncClient, organization_id: str
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    doc_id = str(uuid.uuid4())
    first_chunk = {
        "id": str(uuid.uuid4()),
        "text": "Initial context",
        "score": 0.4,
        "metadata": {"chunk_index": 1},
        "document_id": doc_id,
        "document_name": "upload://contract.pdf",
    }
    second_chunk = {
        "id": str(uuid.uuid4()),
        "text": "Guarantor table with INN values",
        "score": 0.8,
        "metadata": {"chunk_index": 65},
        "document_id": doc_id,
        "document_name": "upload://contract.pdf",
    }
    retriever_mock = AsyncMock(side_effect=[[first_chunk], [first_chunk, second_chunk]])
    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock(
        side_effect=[
            {
                "answer": "В предоставленных источниках ответа нет.",
                "trace": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
            },
            {
                "answer": "The guarantor table includes INN values. [2]",
                "trace": {"usage": {"prompt_tokens": 30, "completion_tokens": 12}},
            },
        ]
    )
    generator_cls = MagicMock(return_value=gen_instance)

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_ask_get_plugin([], generator_cls, retriever_mock),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "Who are the guarantors?", "top_k": 5},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "The guarantor table includes INN values. [2]"
    assert len(body["chunks"]) == 2
    assert retriever_mock.await_count == 2
    assert gen_instance.generate.await_count == 2
    first_query = retriever_mock.await_args_list[0].kwargs["query"]
    retry_query = retriever_mock.await_args_list[1].kwargs["query"]
    assert retry_query != first_query
    assert "Who are the guarantors?" in retry_query
    assert len(gen_instance.generate.await_args_list[1].kwargs["contexts"]) == 2


def test_default_ask_retry_query_expands_guarantor_terms() -> None:
    from ragp_api.api.v1.routes_datasets import _build_default_ask_retry_query

    retry_query = _build_default_ask_retry_query(
        "Выпиши всех поручителей и договоры поручения",
        [{"text": "unrelated context"}],
    )

    assert "поручительство" in retry_query
    assert "договор поручительства" in retry_query
    assert "7.2.1" in retry_query


@pytest.mark.asyncio
async def test_ask_consumes_query_quota_when_enforced(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    await _grant_test_subscription(db_session, organization_id)
    dataset_id = await _create_dataset(client, organization_id)
    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": "Relevant context",
            "score": 0.9,
            "metadata": {},
            "document_id": str(uuid.uuid4()),
            "document_name": "doc.txt",
        }
    ]
    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock(
        return_value={
            "answer": "Answer",
            "trace": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        }
    )
    generator_cls = MagicMock(return_value=gen_instance)

    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        with patch(
            "ragp_api.api.v1.routes_datasets.get_plugin",
            side_effect=_make_ask_get_plugin(fake_chunks, generator_cls),
        ):
            resp = await client.post(
                f"/api/v1/datasets/{dataset_id}/ask",
                headers={"X-Organization-Id": organization_id},
                json={"query": "anything"},
            )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    subscription = (
        await db_session.execute(
            select(OrgSubscription).where(OrgSubscription.org_id == organization_id)
        )
    ).scalar_one()
    assert subscription.q_used == 1


@pytest.mark.asyncio
async def test_ask_returns_chunks_when_generator_fails(
    client: AsyncClient, organization_id: str
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    doc_id = str(uuid.uuid4())
    fake_chunks = [
        {
            "id": str(uuid.uuid4()),
            "text": "Relevant context",
            "score": 0.02,
            "metadata": {"chunk_index": 0},
            "document_id": doc_id,
            "document_name": "upload://context.txt",
        },
    ]

    gen_instance = MagicMock()
    gen_instance.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    generator_cls = MagicMock(return_value=gen_instance)

    with patch(
        "ragp_api.api.v1.routes_datasets.get_plugin",
        side_effect=_make_ask_get_plugin(fake_chunks, generator_cls),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "anything", "top_k": 5},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["chunks"]) == 1
    assert "генерация ответа сейчас недоступна" in body["answer"]
    assert body["usage"]["prompt_tokens"] == 0
    assert body["usage"]["completion_tokens"] == 0


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
async def test_generate_golden_returns_502_when_llm_generation_fails(
    client: AsyncClient,
    organization_id: str,
) -> None:
    from ragp_api.services.golden_qa_generator import GoldenGenerationError

    dataset_id = await _create_dataset(client, organization_id)

    with patch(
        "ragp_api.api.v1.routes_datasets.generate_golden_qa",
        new=AsyncMock(side_effect=GoldenGenerationError("LLM unavailable")),
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/golden",
            headers={"X-Organization-Id": organization_id},
            json={"sample_size": 1},
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "golden_generation_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path_suffix",
    [
        "/golden",
        "/golden/regenerate",
    ],
)
async def test_golden_generation_requires_active_plan_before_llm_call(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
    path_suffix: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    existing_item_id = str(uuid.uuid4())
    db_session.add(
        DatasetGoldenItem(
            id=existing_item_id,
            dataset_id=dataset_id,
            question="existing q",
            answer="existing a",
        )
    )
    await db_session.commit()

    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    generator_mock = AsyncMock(return_value=[])
    try:
        with patch("ragp_api.api.v1.routes_datasets.generate_golden_qa", new=generator_mock):
            resp = await client.post(
                f"/api/v1/datasets/{dataset_id}{path_suffix}",
                headers={"X-Organization-Id": organization_id},
                json={"sample_size": 1},
            )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["code"] == "no_active_plan"
    generator_mock.assert_not_awaited()
    db_session.expire_all()
    existing_item = (
        await db_session.execute(
            select(DatasetGoldenItem).where(DatasetGoldenItem.id == existing_item_id)
        )
    ).scalar_one_or_none()
    assert existing_item is not None


@pytest.mark.asyncio
async def test_golden_generation_returns_402_when_service_quota_exhausts_mid_batch(
    client: AsyncClient,
    db_session,  # type: ignore[no-untyped-def]
    organization_id: str,
) -> None:
    from ragp_api.services.subscription import QuotaExceededError

    await _grant_test_subscription(db_session, organization_id, included_q=1)
    dataset_id = await _create_dataset(client, organization_id)

    old_enforce = settings.enforce_subscription_quotas
    settings.enforce_subscription_quotas = True
    try:
        with patch(
            "ragp_api.api.v1.routes_datasets.generate_golden_qa",
            new=AsyncMock(side_effect=QuotaExceededError(q_used=1, q_limit=1)),
        ):
            resp = await client.post(
                f"/api/v1/datasets/{dataset_id}/golden",
                headers={"X-Organization-Id": organization_id},
                json={"sample_size": 2},
            )
    finally:
        settings.enforce_subscription_quotas = old_enforce

    assert resp.status_code == 402, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["q_used"] == 1
    assert detail["q_limit"] == 1


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
    assert body["run_id"]
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["prompt_tokens"] == 55
    assert body["usage"]["completion_tokens"] == 15
    persisted_run = (
        await db_session.execute(select(Run).where(Run.id == body["run_id"]))
    ).scalar_one()
    assert persisted_run.pipeline_version_id == version_id
    assert persisted_run.dataset_id == dataset_id


@pytest.mark.asyncio
async def test_ask_with_missing_pipeline_id_returns_404_without_default_fallback(
    client: AsyncClient,
    organization_id: str,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    generator_cls = MagicMock()

    with (
        patch(
            "ragp_api.api.v1.routes_datasets.get_plugin",
            side_effect=_make_ask_get_plugin([], generator_cls),
        ),
        patch(
            "ragp_api.api.v1.routes_datasets.run_pipeline",
            new=AsyncMock(return_value=_mock_pipeline_result()),
        ) as run_mock,
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "what?", "pipeline_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "pipeline_not_found"
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pipeline_org_id", "pipeline_dataset_matches"),
    [
        ("other-org", True),
        ("org-test-001", False),
    ],
)
async def test_ask_with_unusable_pipeline_returns_404_without_default_fallback(
    client: AsyncClient,
    organization_id: str,
    db_session,  # type: ignore[no-untyped-def]
    pipeline_org_id: str,
    pipeline_dataset_matches: bool,
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    pipeline_dataset_id = (
        dataset_id
        if pipeline_dataset_matches
        else await _create_dataset(client, organization_id, name="Other DS")
    )
    version_id = str(uuid.uuid4())
    pipeline_id = str(uuid.uuid4())
    db_session.add(
        PipelineVersion(
            id=version_id,
            pipeline_id=pipeline_id,
            nodes_json=[
                {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}}
            ],
        )
    )
    db_session.add(
        Pipeline(
            id=pipeline_id,
            organization_id=pipeline_org_id,
            name="Unusable Pipeline",
            dataset_id=pipeline_dataset_id,
            current_version_id=version_id,
        )
    )
    await db_session.commit()
    generator_cls = MagicMock()

    with (
        patch(
            "ragp_api.api.v1.routes_datasets.get_plugin",
            side_effect=_make_ask_get_plugin([], generator_cls),
        ),
        patch(
            "ragp_api.api.v1.routes_datasets.run_pipeline",
            new=AsyncMock(return_value=_mock_pipeline_result()),
        ) as run_mock,
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "what?", "pipeline_id": pipeline_id},
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "pipeline_not_found"
    run_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ask_with_pipeline_without_current_version_returns_422_without_default_fallback(
    client: AsyncClient,
    organization_id: str,
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    dataset_id = await _create_dataset(client, organization_id)
    pipeline_id = str(uuid.uuid4())
    db_session.add(
        Pipeline(
            id=pipeline_id,
            organization_id=organization_id,
            name="Draft Pipeline",
            dataset_id=dataset_id,
            current_version_id=None,
        )
    )
    await db_session.commit()
    generator_cls = MagicMock()

    with (
        patch(
            "ragp_api.api.v1.routes_datasets.get_plugin",
            side_effect=_make_ask_get_plugin([], generator_cls),
        ),
        patch(
            "ragp_api.api.v1.routes_datasets.run_pipeline",
            new=AsyncMock(return_value=_mock_pipeline_result()),
        ) as run_mock,
    ):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/ask",
            headers={"X-Organization-Id": organization_id},
            json={"query": "what?", "pipeline_id": pipeline_id},
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "pipeline_has_no_current_version"
    run_mock.assert_not_awaited()


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
    assert body["document_id"]
    assert body["status"] == "pending"


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
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["document_id"]
    assert body["status"] == "pending"


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
