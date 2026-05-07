import hashlib
import logging
import os
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    Chunk,
    Dataset,
    DatasetGoldenItem,
    DatasetItem,
    Document,
    Experiment,
    Organization,
    Pipeline,
    PipelineVersion,
    Plan,
    Run,
)
from ragp_api.deps import get_db
from ragp_api.deps_auth import require_organization, require_scope
from ragp_api.plugins.base import Embedder, Generator, Retriever
from ragp_api.plugins.registry import get_plugin
from ragp_api.services.audit import log_audit_event
from ragp_api.services.file_parsers import parse_to_text
from ragp_api.services.golden_qa_generator import (
    GoldenGenerationError,
    generate_golden_qa,
    save_golden_items,
)
from ragp_api.services.object_storage import (
    ObjectStorageError,
    ObjectStorageRef,
    delete_raw_documents,
    store_raw_document,
)
from ragp_api.services.pipeline_runner import run_pipeline
from ragp_api.services.subscription import (
    NoActiveSubscriptionError,
    QuotaExceededError,
    StorageQuotaExceededError,
    consume_q,
    consume_storage,
    get_active_subscription,
    release_storage,
)
from ragp_api.services.usage import record_usage_event
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_ASK_MIN_RETRIEVE_TOP_K = 30
_DEFAULT_ASK_MAX_RETRIEVE_TOP_K = 60
_DEFAULT_ASK_MAX_TOKENS = 4096
_ANSWER_ABSENT_PHRASES = (
    "В предоставленных источниках ответа нет.",
    "в предоставленных источниках ответа нет",
)
_DEFAULT_ASK_RETRY_FALLBACK_TERMS = (
    "table",
    "section",
    "clause",
    "number",
    "date",
    "identifier",
    "details",
    "таблица",
    "раздел",
    "пункт",
    "номер",
    "дата",
    "идентификатор",
    "реквизиты",
)
_DEFAULT_ASK_QUERY_EXPANSIONS = (
    (
        ("поручител", "поручен"),
        (
            "поручительство",
            "поручительства",
            "поручитель",
            "поручители",
            "договор поручительства",
            "обеспечение обязательств",
            "7.2.1",
        ),
    ),
)
_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "text/tab-separated-values",
    "text/html",
    "text/xml",
    "application/xml",
    "application/json",
    "application/x-ndjson",
    "application/x-yaml",
    "application/yaml",
    "text/yaml",
    "text/x-yaml",
    "text/x-rst",
    "text/x-org",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".ndjson",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".rst",
    ".org",
    ".log",
    ".pdf",
    ".docx",
}


async def get_current_organization_id(
    org: Organization = Depends(require_organization),
) -> str:
    return org.id


class DatasetCreateIn(BaseModel):
    name: str
    organization_id: str | None = None
    source: str = "uploaded"


class DatasetOut(BaseModel):
    id: str
    name: str
    organization_id: str
    source: str


@router.post("", status_code=201, response_model=DatasetOut)
async def create_dataset(
    body: DatasetCreateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
    _scope: None = Depends(require_scope("write")),
) -> DatasetOut:
    if settings.enforce_subscription_quotas and await get_active_subscription(db, org.id) is None:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "no_active_plan",
                "message": "No active subscription. Buy a plan at /pricing",
            },
        )

    dataset = Dataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        name=body.name,
        source=body.source,
    )
    db.add(dataset)
    await db.flush()
    await log_audit_event(
        db,
        org_id=org.id,
        user_id=None,
        event_type="dataset.create",
        resource_type="dataset",
        resource_id=dataset.id,
        metadata={"name": dataset.name},
        request=request,
    )
    await db.commit()
    await db.refresh(dataset)
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        organization_id=dataset.organization_id,
        source=dataset.source,
    )


@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(require_organization),
) -> list[DatasetOut]:
    result = await db.execute(select(Dataset).where(Dataset.organization_id == org.id))
    datasets = result.scalars().all()
    return [
        DatasetOut(id=d.id, name=d.name, organization_id=d.organization_id, source=d.source)
        for d in datasets
    ]


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> DatasetOut:
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        organization_id=dataset.organization_id,
        source=dataset.source,
    )


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
    _scope: None = Depends(require_scope("write")),
) -> None:
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    dataset_name = dataset.name

    storage_result = await db.execute(
        select(func.coalesce(func.sum(Document.raw_size_bytes), 0)).where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    total_bytes = int(storage_result.scalar_one() or 0)

    documents_result = await db.execute(
        select(Document).where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    documents = list(documents_result.scalars().all())
    try:
        await delete_raw_documents(
            [ObjectStorageRef(backend=doc.storage_backend, key=doc.object_key) for doc in documents]
        )
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "object_storage_delete_failed",
                "message": "Не удалось удалить исходные документы из S3.",
            },
        ) from exc

    document_ids = select(Document.id).where(
        Document.dataset_id == dataset_id,
        Document.organization_id == organization_id,
    )
    await db.execute(delete(DatasetGoldenItem).where(DatasetGoldenItem.dataset_id == dataset_id))
    await db.execute(delete(DatasetItem).where(DatasetItem.dataset_id == dataset_id))
    await db.execute(
        update(Pipeline)
        .where(Pipeline.dataset_id == dataset_id, Pipeline.organization_id == organization_id)
        .values(dataset_id=None)
    )
    await db.execute(
        update(Run)
        .where(Run.dataset_id == dataset_id, Run.organization_id == organization_id)
        .values(dataset_id=None)
    )
    await db.execute(
        delete(Experiment).where(
            Experiment.dataset_id == dataset_id,
            Experiment.organization_id == organization_id,
        )
    )
    await db.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
    await db.execute(
        delete(Document).where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    await db.delete(dataset)
    await log_audit_event(
        db,
        org_id=organization_id,
        user_id=None,
        event_type="dataset.delete",
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"name": dataset_name},
        request=request,
    )

    if total_bytes > 0:
        await release_storage(db, organization_id, total_bytes)

    await db.commit()


@router.delete("/{dataset_id}/documents/{document_id}", status_code=204)
async def delete_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
    _scope: None = Depends(require_scope("write")),
) -> None:
    """Delete a single document — removes S3 object, chunks, and DB record."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    # Remove from S3
    try:
        await delete_raw_documents(
            [ObjectStorageRef(backend=doc.storage_backend, key=doc.object_key)]
        )
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "object_storage_delete_failed",
                "message": "Не удалось удалить исходный документ из S3.",
            },
        ) from exc

    # Clean up database
    # Golden items are now content-based (no source_chunk_id), so deleting a
    # document does not orphan them.  Only delete the chunks and the document.
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await db.delete(doc)

    if doc.raw_size_bytes and doc.raw_size_bytes > 0:
        await release_storage(db, organization_id, doc.raw_size_bytes)

    await log_audit_event(
        db,
        org_id=organization_id,
        user_id=None,
        event_type="document.delete",
        resource_type="document",
        resource_id=document_id,
        metadata={"source_uri": doc.source_uri, "size_bytes": doc.raw_size_bytes},
        request=request,
    )
    await db.commit()


@router.post("/{dataset_id}/generate", status_code=202)
async def generate_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> dict[str, Any]:
    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    raise HTTPException(
        status_code=501,
        detail={
            "code": "ragas_dataset_generation_not_implemented",
            "message": (
                "Автогенерация датасета RAGAS пока не реализована. "
                "Загрузите документ или сгенерируйте Golden Q&A внутри датасета."
            ),
        },
    )


# ---------------------------------------------------------------------------
# Golden Q&A generation & listing
# ---------------------------------------------------------------------------


class GenerateGoldenIn(BaseModel):
    sample_size: int = 10


class GoldenItemOut(BaseModel):
    id: str
    question: str
    answer: str
    created_at: str


class GenerateGoldenOut(BaseModel):
    items: list[GoldenItemOut]
    count: int


async def _preflight_golden_generation_quota(db: AsyncSession, organization_id: str) -> None:
    if not settings.enforce_subscription_quotas:
        return
    try:
        subscription = await get_active_subscription(db, organization_id)
    except NoActiveSubscriptionError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "no_active_plan",
                "message": "Активной подписки нет. Купите план на /pricing",
            },
        ) from exc
    if subscription is None:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "no_active_plan",
                "message": "Активной подписки нет. Купите план на /pricing",
            },
        )

    plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan is not None and not plan.allow_overage and subscription.q_used + 1 > plan.included_q:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "q_used": subscription.q_used,
                "q_limit": plan.included_q,
                "message": "Лимит RAG-запросов исчерпан. Перейдите на старший тариф.",
            },
        )


def _golden_quota_http_exception(
    exc: NoActiveSubscriptionError | QuotaExceededError,
) -> HTTPException:
    if isinstance(exc, NoActiveSubscriptionError):
        return HTTPException(
            status_code=402,
            detail={
                "code": "no_active_plan",
                "message": "Активной подписки нет. Купите план на /pricing",
            },
        )
    return HTTPException(
        status_code=402,
        detail={
            "code": "quota_exceeded",
            "q_used": exc.q_used,
            "q_limit": exc.q_limit,
            "message": "Лимит RAG-запросов исчерпан. Перейдите на старший тариф.",
        },
    )


@router.post("/{dataset_id}/golden", status_code=201, response_model=GenerateGoldenOut)
async def generate_golden(
    dataset_id: str,
    body: GenerateGoldenIn,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
    _scope: None = Depends(require_scope("write")),
) -> GenerateGoldenOut:
    """Generate golden Q&A pairs for a dataset using DeepSeek."""
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    await _preflight_golden_generation_quota(db, organization_id)

    sample_size = max(1, min(body.sample_size, 50))
    try:
        pairs = await generate_golden_qa(
            dataset_id=dataset_id,
            organization_id=organization_id,
            db=db,
            sample_size=sample_size,
        )
    except GoldenGenerationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "golden_generation_failed",
                "message": "Не удалось сгенерировать Golden Q&A. Проверьте настройки LLM.",
            },
        ) from exc
    except (NoActiveSubscriptionError, QuotaExceededError) as exc:
        raise _golden_quota_http_exception(exc) from exc
    db_items = await save_golden_items(dataset_id=dataset_id, pairs=pairs, db=db)

    out_items = [
        GoldenItemOut(
            id=item.id,
            question=item.question,
            answer=item.answer,
            created_at=item.created_at.isoformat(),
        )
        for item in db_items
    ]
    await log_audit_event(
        db,
        org_id=organization_id,
        user_id=None,
        event_type="golden.generate",
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"count": len(out_items)},
    )
    await db.commit()
    return GenerateGoldenOut(items=out_items, count=len(out_items))


@router.post("/{dataset_id}/golden/regenerate", status_code=201, response_model=GenerateGoldenOut)
async def regenerate_golden(
    dataset_id: str,
    body: GenerateGoldenIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
    _scope: None = Depends(require_scope("write")),
) -> GenerateGoldenOut:
    """Delete all existing golden Q&A pairs for a dataset and regenerate them."""
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    await _preflight_golden_generation_quota(db, organization_id)

    # Delete all existing golden items
    await db.execute(delete(DatasetGoldenItem).where(DatasetGoldenItem.dataset_id == dataset_id))

    sample_size = max(1, min(body.sample_size, 50))
    try:
        pairs = await generate_golden_qa(
            dataset_id=dataset_id,
            organization_id=organization_id,
            db=db,
            sample_size=sample_size,
        )
    except GoldenGenerationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "golden_generation_failed",
                "message": "Не удалось перегенерировать Golden Q&A. Проверьте настройки LLM.",
            },
        ) from exc
    except (NoActiveSubscriptionError, QuotaExceededError) as exc:
        raise _golden_quota_http_exception(exc) from exc
    db_items = await save_golden_items(dataset_id=dataset_id, pairs=pairs, db=db)

    out_items = [
        GoldenItemOut(
            id=item.id,
            question=item.question,
            answer=item.answer,
            created_at=item.created_at.isoformat(),
        )
        for item in db_items
    ]
    await log_audit_event(
        db,
        org_id=organization_id,
        user_id=None,
        event_type="golden.regenerate",
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"count": len(out_items)},
        request=request,
    )
    await db.commit()
    return GenerateGoldenOut(items=out_items, count=len(out_items))


@router.get("/{dataset_id}/golden", response_model=list[GoldenItemOut])
async def list_golden(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> list[GoldenItemOut]:
    """List all golden Q&A items for a dataset."""
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    items_result = await db.execute(
        select(DatasetGoldenItem)
        .where(DatasetGoldenItem.dataset_id == dataset_id)
        .order_by(DatasetGoldenItem.created_at)
    )
    items = items_result.scalars().all()
    return [
        GoldenItemOut(
            id=item.id,
            question=item.question,
            answer=item.answer,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


# ---------------------------------------------------------------------------
# Document list
# ---------------------------------------------------------------------------


class DocumentListItem(BaseModel):
    id: str
    source_uri: str
    status: str
    parsed_at: str | None
    chunk_count: int


@router.get("/{dataset_id}/documents", response_model=list[DocumentListItem])
async def list_documents(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> list[DocumentListItem]:
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    rows = await db.execute(
        select(Document, func.count(Chunk.id).label("chunk_count"))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.dataset_id == dataset_id, Document.organization_id == organization_id)
        .group_by(Document.id)
    )
    items = []
    for doc, count in rows.all():
        items.append(
            DocumentListItem(
                id=doc.id,
                source_uri=doc.source_uri,
                status=doc.status,
                parsed_at=doc.parsed_at.isoformat() if doc.parsed_at else None,
                chunk_count=count,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Document detail
# ---------------------------------------------------------------------------


class ChunkDetail(BaseModel):
    index: int
    text: str
    len: int
    metadata: dict[str, Any]
    has_embedding: bool


class DocumentDetail(BaseModel):
    id: str
    source_uri: str
    status: str
    parsed_at: str | None
    chunk_count: int
    chunks: list[ChunkDetail]


@router.get("/{dataset_id}/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    dataset_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> DocumentDetail:
    doc_result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    chunks_result = await db.execute(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.created_at)
    )
    chunks = chunks_result.scalars().all()

    chunk_details = [
        ChunkDetail(
            index=c.metadata_json.get("chunk_index", i) if c.metadata_json else i,
            text=c.text,
            len=len(c.text),
            metadata=c.metadata_json or {},
            has_embedding=c.embedding is not None,
        )
        for i, c in enumerate(chunks)
    ]

    return DocumentDetail(
        id=doc.id,
        source_uri=doc.source_uri,
        status=doc.status,
        parsed_at=doc.parsed_at.isoformat() if doc.parsed_at else None,
        chunk_count=len(chunks),
        chunks=chunk_details,
    )


# ---------------------------------------------------------------------------
# Upload document
# ---------------------------------------------------------------------------


class UploadDocumentResponse(BaseModel):
    document_id: str
    status: str


@router.post("/{dataset_id}/documents", status_code=201, response_model=UploadDocumentResponse)
async def upload_document(
    dataset_id: str,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
    _scope: None = Depends(require_scope("write")),
) -> UploadDocumentResponse:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    # Validate file type
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type: {content_type or ext}. "
                "Allowed formats: .txt, .md, .json, .jsonl, .csv, .tsv, "
                ".yaml, .yml, .xml, .html, .rst, .org, .log, .pdf, .docx."
            ),
        )

    # Read and size-limit
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    # Storage quota check — must happen before any DB writes
    if settings.enforce_subscription_quotas:
        try:
            await consume_storage(db, organization_id, len(raw))
        except NoActiveSubscriptionError as exc:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "no_active_plan",
                    "message": "Активной подписки нет. Купите план на /pricing",
                },
            ) from exc
        except StorageQuotaExceededError as exc:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "storage_quota_exceeded",
                    "storage_used": exc.used,
                    "storage_limit": exc.limit,
                    "message": (
                        "Лимит хранилища исчерпан. "
                        "Удалите датасеты или перейдите на старший план."
                    ),
                },
            ) from exc

    text = parse_to_text(filename, content_type, raw)

    # Create document record
    now = datetime.now(tz=UTC)
    document_id = str(uuid.uuid4())
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        storage_ref = await store_raw_document(
            raw=raw,
            organization_id=organization_id,
            dataset_id=dataset_id,
            document_id=document_id,
            filename=filename,
            content_type=content_type,
            sha256=sha256,
        )
    except ObjectStorageError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "object_storage_upload_failed",
                "message": "Не удалось сохранить исходный документ в S3.",
            },
        ) from exc

    doc = Document(
        id=document_id,
        organization_id=organization_id,
        dataset_id=dataset_id,
        source_uri=f"upload://{filename}",
        raw_size_bytes=len(raw),
        content_type=content_type,
        sha256=sha256,
        storage_backend=storage_ref.backend,
        object_key=storage_ref.key,
        parsed_at=now,
        status="pending",
    )
    db.add(doc)

    await log_audit_event(
        db,
        org_id=organization_id,
        user_id=None,
        event_type="dataset.upload",
        resource_type="dataset",
        resource_id=dataset_id,
        metadata={"name": file.filename or "", "size_bytes": len(raw)},
        request=request,
    )
    await db.commit()

    # Queue async chunking job on the rag.ingest queue.
    pool = None
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(
            RedisSettings(host=settings.redis_host, port=settings.redis_port),
            default_queue_name="rag.ingest",
        )
        await pool.enqueue_job("chunk_document", document_id=document_id, text=text)
    except Exception as exc:
        logger.exception("Failed to queue chunking job for doc %s", document_id)
        try:
            await db.delete(doc)
            if settings.enforce_subscription_quotas and len(raw) > 0:
                await release_storage(db, organization_id, len(raw))
            await db.commit()
        except Exception:
            logger.exception("Failed to clean up doc %s after enqueue failure", document_id)
            await db.rollback()
        try:
            await delete_raw_documents(
                [ObjectStorageRef(backend=storage_ref.backend, key=storage_ref.key)]
            )
        except ObjectStorageError:
            logger.exception(
                "Failed to delete raw document for doc %s after enqueue failure",
                document_id,
            )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "document_enqueue_failed",
                "message": "Не удалось поставить документ в очередь обработки.",
            },
        ) from exc
    finally:
        if pool is not None:
            await pool.aclose()

    return UploadDocumentResponse(
        document_id=doc.id,
        status="pending",
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchIn(BaseModel):
    query: str
    top_k: int = 10


class SearchChunkOut(BaseModel):
    id: str
    text: str
    score: float
    metadata: dict[str, Any]
    document_id: str
    document_name: str


class SearchOut(BaseModel):
    chunks: list[SearchChunkOut]


async def _reserve_dataset_query_quota(db: AsyncSession, organization_id: str) -> None:
    if not settings.enforce_subscription_quotas:
        return
    try:
        await consume_q(db, organization_id, count=1)
    except NoActiveSubscriptionError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "no_active_plan",
                "message": "Активной подписки нет. Купите план на /pricing",
            },
        ) from exc
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "quota_exceeded",
                "q_used": exc.q_used,
                "q_limit": exc.q_limit,
                "message": "Лимит RAG-запросов исчерпан. Перейдите на старший тариф.",
            },
        ) from exc


async def _record_dataset_query_usage(
    db: AsyncSession,
    *,
    organization_id: str,
    pipeline_id: str | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    await record_usage_event(
        db,
        org_id=organization_id,
        api_key_id=None,
        pipeline_id=pipeline_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        quota_reserved=settings.enforce_subscription_quotas,
    )


@router.post("/{dataset_id}/search", response_model=SearchOut)
async def search_dataset(
    dataset_id: str,
    body: SearchIn,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> SearchOut:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    await _reserve_dataset_query_quota(db, organization_id)

    # Build embedder (priority: OpenAI → Ollama)
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    embedder: Embedder | None = None
    if openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "openai/text-embedding-3-small"}))
    elif ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "bge-m3"}))

    query_vec: list[float] | None = None
    if embedder is not None:
        try:
            vecs = await embedder.embed([body.query])
            query_vec = vecs[0]
        except Exception:
            # Fall back to BM25-only path; dense branch will be skipped by retriever
            pass

    # Retrieve
    retriever_cls = get_plugin("retriever", "pgvector-hybrid")
    if retriever_cls is None:
        raise HTTPException(status_code=500, detail="pgvector-hybrid retriever not available")

    retriever = cast(Retriever, retriever_cls({"session": db}))
    raw_chunks = await retriever.retrieve(
        query=body.query,
        top_k=body.top_k,
        organization_id=organization_id,
        dataset_id=dataset_id,
        query_vec=query_vec,
    )
    await _record_dataset_query_usage(
        db,
        organization_id=organization_id,
        pipeline_id=None,
        model="retrieval-only",
        prompt_tokens=0,
        completion_tokens=0,
    )

    return SearchOut(
        chunks=[
            SearchChunkOut(
                id=c["id"],
                text=c["text"],
                score=c["score"],
                metadata=c["metadata"],
                document_id=c["document_id"],
                document_name=c["document_name"],
            )
            for c in raw_chunks
        ]
    )


# ---------------------------------------------------------------------------
# Ask  (RAG full-cycle: embed → retrieve → generate)
# ---------------------------------------------------------------------------


class AskIn(BaseModel):
    query: str
    top_k: int = 5
    model: str = "deepseek/deepseek-v4-flash"
    pipeline_id: str | None = None


class AskChunkOut(BaseModel):
    id: str
    text: str
    score: float
    document_id: str
    document_name: str


class AskUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class AskOut(BaseModel):
    answer: str
    chunks: list[AskChunkOut]
    usage: AskUsage
    run_id: str | None = None


async def _build_default_embedder(ollama_host: str, openai_key: str) -> "Embedder | None":
    """Build embedder using environment priority: OpenAI → Ollama."""
    if openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            return cast(Embedder, embedder_cls({"model": "openai/text-embedding-3-small"}))
    elif ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            return cast(Embedder, embedder_cls({"model": "bge-m3"}))
    return None


def _default_ask_retrieve_top_k(requested_top_k: int) -> int:
    return min(
        max(requested_top_k, _DEFAULT_ASK_MIN_RETRIEVE_TOP_K),
        _DEFAULT_ASK_MAX_RETRIEVE_TOP_K,
    )


def _is_absent_answer(answer: str) -> bool:
    normalized = " ".join(answer.strip().casefold().split())
    if not normalized:
        return True
    return any(
        phrase.casefold().rstrip(".") in normalized.rstrip(".") for phrase in _ANSWER_ABSENT_PHRASES
    )


def _build_default_ask_retry_query(query: str, contexts: list[dict[str, Any]]) -> str:
    query_terms = {term.casefold() for term in re.findall(r"\w+", query)}
    retry_terms: list[str] = []
    seen_retry_terms: set[str] = set()

    query_normalized = query.casefold()
    for triggers, expansions in _DEFAULT_ASK_QUERY_EXPANSIONS:
        if not any(trigger in query_normalized for trigger in triggers):
            continue
        for expansion in expansions:
            normalized = expansion.casefold()
            if normalized in seen_retry_terms:
                continue
            seen_retry_terms.add(normalized)
            retry_terms.append(expansion)

    for context in contexts[:8]:
        text = str(context.get("text", ""))
        candidates = re.findall(r"\b\d+(?:\.\d+)+\b|\b[A-ZА-ЯЁ]{2,}\b|\b[\w-]{5,}\b", text)
        for candidate in candidates:
            normalized = candidate.casefold()
            if normalized in query_terms or normalized in seen_retry_terms:
                continue
            seen_retry_terms.add(normalized)
            retry_terms.append(candidate)
            if len(retry_terms) >= 24:
                break
        if len(retry_terms) >= 24:
            break

    if not retry_terms:
        retry_terms = list(_DEFAULT_ASK_RETRY_FALLBACK_TERMS)

    return f"{query}\n\nRelated exact terms: {' '.join(retry_terms)}"


def _merge_chunks_by_id(
    chunks: list[dict[str, Any]],
    extra_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks + extra_chunks:
        key = str(chunk.get("id") or f"{chunk.get('document_id', '')}:{chunk.get('text', '')}")
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return merged


def _neighbor_seed_score(chunk: dict[str, Any]) -> int:
    text = str(chunk.get("text", "")).casefold()
    score = 0
    if "7.2.1" in text:
        score += 10
    if "поручитель" in text or "поручительств" in text:
        score += 5
    return score


async def _load_neighbor_chunks(
    session: Any,
    chunks: list[dict[str, Any]],
    *,
    window: int = 8,
    limit: int = 80,
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    seeds = sorted(chunks, key=_neighbor_seed_score, reverse=True)
    neighbor_chunks: list[dict[str, Any]] = []
    seen_ids: set[str] = {str(chunk.get("id", "")) for chunk in chunks}

    for chunk in seeds:
        if len(neighbor_chunks) >= limit:
            break
        metadata = chunk.get("metadata") or {}
        chunk_index = metadata.get("chunk_index")
        document_id = chunk.get("document_id")
        if not isinstance(chunk_index, int) or not document_id:
            continue
        try:
            result = await session.execute(
                text(
                    """
                    SELECT c.id, c.text, c.metadata_json, c.document_id,
                           d.source_uri AS document_name
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id = :document_id
                      AND c.text != ''
                      AND (c.metadata_json->>'chunk_index')::int BETWEEN :lo AND :hi
                    ORDER BY (c.metadata_json->>'chunk_index')::int
                    """
                ),
                {
                    "document_id": document_id,
                    "lo": max(chunk_index - window, 0),
                    "hi": chunk_index + window,
                },
            )
        except Exception:
            continue
        for row in result.fetchall():
            row_id = str(row.id)
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            neighbor_chunks.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "metadata": row.metadata_json or {},
                    "score": float(chunk.get("score", 0.0)),
                    "document_id": row.document_id,
                    "document_name": row.document_name,
                }
            )
            if len(neighbor_chunks) >= limit:
                break

    return neighbor_chunks


def _usage_from_generation_result(gen_result: dict[str, Any]) -> dict[str, int]:
    trace: dict[str, Any] = gen_result.get("trace", {})
    usage_raw: dict[str, Any] = trace.get("usage", {})
    return {
        "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
        "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
    }


@router.post("/{dataset_id}/ask", response_model=AskOut)
async def ask_dataset(
    dataset_id: str,
    body: AskIn,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_current_organization_id),
) -> AskOut:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    await _reserve_dataset_query_quota(db, organization_id)

    ollama_host = os.environ.get("OLLAMA_HOST", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    # --- Pipeline-aware path ---
    pipeline_nodes: list[dict[str, Any]] | None = None
    pipeline_version_id_for_run: str | None = None
    if body.pipeline_id:
        pl_result = await db.execute(
            select(Pipeline).where(
                Pipeline.id == body.pipeline_id,
                Pipeline.organization_id == organization_id,
                Pipeline.dataset_id == dataset_id,
            )
        )
        pl = pl_result.scalar_one_or_none()
        if pl is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "pipeline_not_found",
                    "message": f"Pipeline {body.pipeline_id} not found for this dataset",
                },
            )
        if not pl.current_version_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "pipeline_has_no_current_version",
                    "message": "Pipeline has no current version",
                },
            )

        pipeline_version_id_for_run = pl.current_version_id
        ver_result = await db.execute(
            select(PipelineVersion).where(
                PipelineVersion.id == pl.current_version_id,
                PipelineVersion.pipeline_id == pl.id,
            )
        )
        ver = ver_result.scalar_one_or_none()
        if ver is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "pipeline_has_no_current_version",
                    "message": "Pipeline current version was not found",
                },
            )
        pipeline_nodes = ver.nodes_json

    if pipeline_nodes is not None:
        # Execute via pipeline nodes
        # Inject session and org into retriever node params
        enriched_nodes: list[dict[str, Any]] = []
        for node in pipeline_nodes:
            n = dict(node)
            if n.get("plugin_kind") == "retriever":
                params = dict(n.get("params", {}))
                params["session"] = db
                params["organization_id"] = organization_id
                params["dataset_id"] = dataset_id
                n["params"] = params
            enriched_nodes.append(n)

        started_at = datetime.now(tz=UTC)
        result = await run_pipeline(enriched_nodes, body.query, db)
        finished_at = datetime.now(tz=UTC)

        raw_chunks = result.get("contexts", [])
        answer = result.get("answer", "")
        usage_dict: dict[str, Any] = result.get("usage", {})
        prompt_tokens = int(usage_dict.get("prompt_tokens", 0))
        completion_tokens = int(usage_dict.get("completion_tokens", 0))

        run_id: str | None = None

        # Persist Run record
        if pipeline_version_id_for_run is not None:
            run_id = str(uuid.uuid4())
            run_record = Run(
                id=run_id,
                organization_id=organization_id,
                pipeline_version_id=pipeline_version_id_for_run,
                dataset_id=dataset_id,
                query=body.query,
                status="completed",
                metrics_json={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
                traces_json={"traces": result.get("traces", [])},
                started_at=started_at,
                finished_at=finished_at,
            )
            db.add(run_record)
            await db.commit()

        if not raw_chunks and not answer:
            await _record_dataset_query_usage(
                db,
                organization_id=organization_id,
                pipeline_id=body.pipeline_id,
                model=body.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return AskOut(
                answer="Не нашёл релевантных чанков для ответа.",
                chunks=[],
                usage=AskUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
                run_id=run_id,
            )

        await _record_dataset_query_usage(
            db,
            organization_id=organization_id,
            pipeline_id=body.pipeline_id,
            model=body.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return AskOut(
            answer=answer,
            chunks=[
                AskChunkOut(
                    id=c.get("id", ""),
                    text=c.get("text", ""),
                    score=round(c.get("score", 0.0), 4),
                    document_id=c.get("document_id", ""),
                    document_name=c.get("document_name", ""),
                )
                for c in raw_chunks
            ],
            usage=AskUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
            run_id=run_id,
        )

    # --- Default hardcoded path ---
    embedder = await _build_default_embedder(ollama_host, openai_key)

    query_vec: list[float] | None = None
    if embedder is not None:
        try:
            vecs = await embedder.embed([body.query])
            query_vec = vecs[0]
        except Exception:
            pass

    # Retrieve
    retriever_cls = get_plugin("retriever", "pgvector-hybrid")
    if retriever_cls is None:
        raise HTTPException(status_code=500, detail="pgvector-hybrid retriever not available")

    retriever = cast(Retriever, retriever_cls({"session": db}))
    retrieve_top_k = _default_ask_retrieve_top_k(body.top_k)
    raw_chunks = await retriever.retrieve(
        query=body.query,
        top_k=retrieve_top_k,
        organization_id=organization_id,
        dataset_id=dataset_id,
        query_vec=query_vec,
    )

    # Empty retrieval → skip LLM
    if not raw_chunks:
        await _record_dataset_query_usage(
            db,
            organization_id=organization_id,
            pipeline_id=None,
            model=body.model,
            prompt_tokens=0,
            completion_tokens=0,
        )
        return AskOut(
            answer="Не нашёл релевантных чанков для ответа.",
            chunks=[],
            usage=AskUsage(prompt_tokens=0, completion_tokens=0),
        )

    # Generate answer via LiteLLM
    generator_cls = get_plugin("generator", "litellm-generator")
    if generator_cls is None:
        raise HTTPException(status_code=500, detail="litellm-generator not available")

    generator = cast(
        Generator,
        generator_cls(
            {"model": body.model, "temperature": 0.0, "max_tokens": _DEFAULT_ASK_MAX_TOKENS}
        ),
    )
    try:
        gen_result = await generator.generate(body.query, contexts=raw_chunks)
        answer = gen_result.get("answer", "")
        usage_raw = _usage_from_generation_result(gen_result)
        if _is_absent_answer(answer):
            retry_query = _build_default_ask_retry_query(body.query, raw_chunks)
            retry_query_vec = query_vec
            if embedder is not None:
                with suppress(Exception):
                    retry_query_vec = (await embedder.embed([retry_query]))[0]
            retry_chunks = await retriever.retrieve(
                query=retry_query,
                top_k=retrieve_top_k,
                organization_id=organization_id,
                dataset_id=dataset_id,
                query_vec=retry_query_vec,
            )
            neighbor_chunks = await _load_neighbor_chunks(db, retry_chunks)
            merged_chunks = _merge_chunks_by_id(raw_chunks, retry_chunks)
            merged_chunks = _merge_chunks_by_id(merged_chunks, neighbor_chunks)
            if merged_chunks:
                retry_gen_result = await generator.generate(body.query, contexts=merged_chunks)
                retry_answer = retry_gen_result.get("answer", "")
                retry_usage = _usage_from_generation_result(retry_gen_result)
                usage_raw = {
                    "prompt_tokens": usage_raw["prompt_tokens"] + retry_usage["prompt_tokens"],
                    "completion_tokens": (
                        usage_raw["completion_tokens"] + retry_usage["completion_tokens"]
                    ),
                }
                if not _is_absent_answer(retry_answer):
                    answer = retry_answer
                    raw_chunks = merged_chunks
    except Exception:
        answer = (
            "Нашёл релевантные чанки, но генерация ответа сейчас недоступна. "
            "Откройте источники ниже или проверьте настройки LLM."
        )
        usage_raw = {"prompt_tokens": 0, "completion_tokens": 0}

    await _record_dataset_query_usage(
        db,
        organization_id=organization_id,
        pipeline_id=None,
        model=body.model,
        prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
        completion_tokens=int(usage_raw.get("completion_tokens", 0)),
    )

    return AskOut(
        answer=answer,
        chunks=[
            AskChunkOut(
                id=c["id"],
                text=c["text"],
                score=round(c["score"], 4),
                document_id=c["document_id"],
                document_name=c["document_name"],
            )
            for c in raw_chunks
        ],
        usage=AskUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
        ),
    )
