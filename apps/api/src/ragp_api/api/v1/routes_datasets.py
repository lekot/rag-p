import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import jsonschema
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, Dataset, Document
from ragp_api.deps import get_db, get_organization_id
from ragp_api.plugins.registry import get_plugin

router = APIRouter(prefix="/datasets", tags=["datasets"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = {"text/plain", "text/markdown"}
_ALLOWED_EXTENSIONS = {".txt", ".md"}


class DatasetCreateIn(BaseModel):
    name: str
    organization_id: str
    source: str = "uploaded"


class DatasetOut(BaseModel):
    id: str
    name: str
    organization_id: str
    source: str


@router.post("", status_code=201, response_model=DatasetOut)
async def create_dataset(
    body: DatasetCreateIn,
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    dataset = Dataset(
        id=str(uuid.uuid4()),
        organization_id=body.organization_id,
        name=body.name,
        source=body.source,
    )
    db.add(dataset)
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
    organization_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[DatasetOut]:
    result = await db.execute(
        select(Dataset).where(Dataset.organization_id == organization_id)
    )
    datasets = result.scalars().all()
    return [
        DatasetOut(id=d.id, name=d.name, organization_id=d.organization_id, source=d.source)
        for d in datasets
    ]


@router.post("/{dataset_id}/generate", status_code=202)
async def generate_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")
    return {"status": "accepted", "dataset_id": dataset_id, "message": "RAGAS generation queued"}


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
    organization_id: str = Depends(get_organization_id),
) -> list[DocumentListItem]:
    ds_result = await db.execute(
        select(Dataset).where(
            Dataset.id == dataset_id, Dataset.organization_id == organization_id
        )
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
    organization_id: str = Depends(get_organization_id),
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
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.created_at)
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

class ChunkPreview(BaseModel):
    index: int
    text: str
    len: int
    metadata: dict[str, Any]


class UploadDocumentResponse(BaseModel):
    document_id: str
    chunk_count: int
    embedded: bool
    chunks_preview: list[ChunkPreview]


@router.post("/{dataset_id}/documents", status_code=201, response_model=UploadDocumentResponse)
async def upload_document(
    dataset_id: str,
    file: UploadFile,
    chunker_name: str = Form(default="recursive-character"),
    chunker_params: str = Form(default="{}"),
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> UploadDocumentResponse:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(
            Dataset.id == dataset_id, Dataset.organization_id == organization_id
        )
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
            detail=f"Unsupported file type: {content_type or ext}. Allowed: .txt, .md",
        )

    # Read and size-limit
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File must be valid UTF-8") from exc

    # Parse chunker params
    try:
        params_override: dict[str, Any] = json.loads(chunker_params)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid chunker_params JSON: {exc}") from exc

    # Resolve chunker plugin
    chunker_cls = get_plugin("chunker", chunker_name)
    if chunker_cls is None:
        raise HTTPException(status_code=422, detail=f"Unknown chunker: {chunker_name}")

    # Validate params against schema
    schema = chunker_cls.params_schema
    default_params: dict[str, Any] = schema.get("default", {})
    merged_params = {**default_params, **params_override}
    try:
        jsonschema.validate(instance=merged_params, schema=schema)
    except jsonschema.ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid chunker params: {exc.message}") from exc

    chunker = chunker_cls(merged_params)

    # Create document record
    now = datetime.now(tz=timezone.utc)
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        dataset_id=dataset_id,
        source_uri=f"upload://{filename}",
        parsed_at=now,
        status="parsed",
    )
    db.add(doc)
    await db.flush()

    # Chunk the text
    raw_chunks = await chunker.chunk(text)

    # Build Chunk objects (embedding NULL for now)
    chunk_objs = []
    for i, rc in enumerate(raw_chunks):
        meta: dict[str, Any] = {"chunk_index": i}
        if isinstance(rc.get("metadata"), dict):
            meta.update(rc["metadata"])
        chunk_objs.append(
            Chunk(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                organization_id=organization_id,
                text=rc["text"],
                embedding=None,
                metadata_json=meta,
            )
        )
    db.add_all(chunk_objs)

    # Pick an embedder by what credentials/services are reachable.
    # Order: local Ollama → Cohere → OpenAI/litellm. All produce 1024-dim by default.
    embedded = False
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    embedder = None
    if ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            embedder = embedder_cls({"model": "bge-m3"})
    elif cohere_key:
        embedder_cls = get_plugin("embedder", "cohere-embedder")
        if embedder_cls is not None:
            embedder = embedder_cls({"model": "embed-multilingual-v3.0", "input_type": "search_document"})
    elif openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            embedder = embedder_cls({"model": "openai/text-embedding-3-small"})
    if embedder is not None:
        try:
            texts = [c.text for c in chunk_objs]
            vectors = await embedder.embed(texts)
            for chunk_obj, vec in zip(chunk_objs, vectors):
                chunk_obj.embedding = vec
            embedded = True
        except Exception:
            # embedding is optional — proceed without it
            pass

    await db.commit()

    # Build preview (first 5 chunks)
    preview = [
        ChunkPreview(
            index=c.metadata_json.get("chunk_index", i) if c.metadata_json else i,
            text=c.text[:200],
            len=len(c.text),
            metadata=c.metadata_json or {},
        )
        for i, c in enumerate(chunk_objs[:5])
    ]

    return UploadDocumentResponse(
        document_id=doc.id,
        chunk_count=len(chunk_objs),
        embedded=embedded,
        chunks_preview=preview,
    )
