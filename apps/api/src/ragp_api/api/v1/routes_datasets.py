import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import jsonschema
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, Dataset, Document
from ragp_api.deps import get_db, get_organization_id
from ragp_api.plugins.base import Chunker, Embedder, Generator, Retriever
from ragp_api.plugins.registry import get_plugin

router = APIRouter(prefix="/datasets", tags=["datasets"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
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
}


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
    result = await db.execute(select(Dataset).where(Dataset.organization_id == organization_id))
    datasets = result.scalars().all()
    return [
        DatasetOut(id=d.id, name=d.name, organization_id=d.organization_id, source=d.source)
        for d in datasets
    ]


@router.post("/{dataset_id}/generate", status_code=202)
async def generate_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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
                "Allowed text formats: .txt, .md, .json, .jsonl, .csv, .tsv, "
                ".yaml, .yml, .xml, .html, .rst, .org, .log."
            ),
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
        raise HTTPException(
            status_code=422, detail=f"Invalid chunker params: {exc.message}"
        ) from exc

    chunker = cast(Chunker, chunker_cls(merged_params))

    # Create document record
    now = datetime.now(tz=UTC)
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
    embedder: Embedder | None = None
    if ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "bge-m3"}))
    elif cohere_key:
        embedder_cls = get_plugin("embedder", "cohere-embedder")
        if embedder_cls is not None:
            embedder = cast(
                Embedder,
                embedder_cls({"model": "embed-multilingual-v3.0", "input_type": "search_document"}),
            )
    elif openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "openai/text-embedding-3-small"}))
    if embedder is not None:
        try:
            texts = [c.text for c in chunk_objs]
            vectors = await embedder.embed(texts)
            for chunk_obj, vec in zip(chunk_objs, vectors, strict=False):
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


@router.post("/{dataset_id}/search", response_model=SearchOut)
async def search_dataset(
    dataset_id: str,
    body: SearchIn,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> SearchOut:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    # Build embedder (same priority as ingest: Ollama → Cohere → OpenAI)
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    embedder: Embedder | None = None
    if ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "bge-m3"}))
    elif cohere_key:
        embedder_cls = get_plugin("embedder", "cohere-embedder")
        if embedder_cls is not None:
            embedder = cast(
                Embedder,
                embedder_cls({"model": "embed-multilingual-v3.0", "input_type": "search_query"}),
            )
    elif openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "openai/text-embedding-3-small"}))

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


@router.post("/{dataset_id}/ask", response_model=AskOut)
async def ask_dataset(
    dataset_id: str,
    body: AskIn,
    db: AsyncSession = Depends(get_db),
    organization_id: str = Depends(get_organization_id),
) -> AskOut:
    # Verify dataset ownership
    ds_result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.organization_id == organization_id)
    )
    if ds_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    # Build embedder (same priority as ingest/search: Ollama → Cohere → OpenAI)
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    embedder: Embedder | None = None
    if ollama_host:
        embedder_cls = get_plugin("embedder", "ollama-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "bge-m3"}))
    elif cohere_key:
        embedder_cls = get_plugin("embedder", "cohere-embedder")
        if embedder_cls is not None:
            embedder = cast(
                Embedder,
                embedder_cls({"model": "embed-multilingual-v3.0", "input_type": "search_query"}),
            )
    elif openai_key:
        embedder_cls = get_plugin("embedder", "litellm-embedder")
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls({"model": "openai/text-embedding-3-small"}))

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
    raw_chunks = await retriever.retrieve(
        query=body.query,
        top_k=body.top_k,
        organization_id=organization_id,
        dataset_id=dataset_id,
        query_vec=query_vec,
    )

    # Empty retrieval → skip LLM
    if not raw_chunks:
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
        generator_cls({"model": body.model, "temperature": 0.0, "max_tokens": 1024}),
    )
    gen_result = await generator.generate(body.query, contexts=raw_chunks)

    answer: str = gen_result.get("answer", "")
    trace: dict[str, Any] = gen_result.get("trace", {})
    usage_raw: dict[str, Any] = trace.get("usage", {})

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
