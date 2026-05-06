"""Generates golden Q&A pairs from document text via DeepSeek API."""

import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, DatasetGoldenItem, Document
from ragp_api.services.subscription import NoActiveSubscriptionError, QuotaExceededError, consume_q
from ragp_api.services.usage import record_usage_event
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_QA_PROMPT = (
    "Read the following text and generate ONE concise question that this text answers, "
    "plus the exact answer.\n"
    'Return JSON: {{"question": "...", "answer": "..."}}.\n'
    "No explanations.\n\n"
    "Text:\n{document_text}"
)

# Take at most this many chars from the start of each document for QA generation.
# 4000 chars ~1000 tokens — leaves room in the context window for the Q&A output.
_DOC_TEXT_MAX_CHARS = 4000


class GoldenGenerationError(RuntimeError):
    """Raised when documents exist but no valid golden Q&A could be generated."""


def _parse_deepseek_response(raw: str) -> dict[str, str] | None:
    """Parse DeepSeek JSON response, stripping markdown fences if present.

    Returns {"question": ..., "answer": ...} or None.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    question = str(parsed.get("question", "")).strip()
    answer = str(parsed.get("answer", "")).strip()
    if not question or not answer:
        return None
    return {"question": question, "answer": answer}


async def _call_deepseek(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> httpx.Response:
    """Single DeepSeek API call — isolated for testability."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await client.post(url, json=body, headers=headers)


def _sample_document_text(document: Document, chunks: Sequence[Chunk]) -> str:
    """Build a text sample from a document for QA generation.

    Uses the first _DOC_TEXT_MAX_CHARS from the reconstructed document text.
    """
    text = "\n\n".join(c.text for c in chunks) if chunks else document.source_uri
    return text[:_DOC_TEXT_MAX_CHARS].strip()


async def generate_golden_qa(
    dataset_id: str,
    organization_id: str,
    db: AsyncSession,
    sample_size: int = 10,
    model: str = "deepseek-v4-flash",
) -> list[dict[str, str]]:
    """Generates golden Q&A pairs by sampling documents from the dataset.

    For each sampled document, takes the first ~4000 chars and asks DeepSeek
    to produce a question+answer pair.  The result is NOT tied to any specific
    chunk — it works across chunkers and survives re-chunking.

    Returns list of {"question": str, "answer": str}.
    """
    # Sample random documents from the dataset
    stmt = (
        select(Document)
        .where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
            Document.status == "indexed",
        )
        .order_by(func.random())
        .limit(sample_size)
    )
    result = await db.execute(stmt)
    documents = result.scalars().all()

    if not documents:
        logger.info(
            "No indexed documents found for dataset %s — returning empty golden set", dataset_id
        )
        return []

    api_key = settings.deepseek_api_key or ""
    base_url = (settings.deepseek_base_url or "https://api.deepseek.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    pairs: list[dict[str, str]] = []
    failures = 0
    for doc in documents:
        # Load chunks for this document
        chunks_result = await db.execute(
            select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.created_at)
        )
        chunks = chunks_result.scalars().all()
        doc_text = _sample_document_text(doc, chunks)
        if not doc_text:
            continue

        prompt = _QA_PROMPT.format(document_text=doc_text)
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        try:
            if settings.enforce_subscription_quotas:
                await consume_q(db, organization_id, count=1)
            resp = await _call_deepseek(url, headers, body)
            if resp.status_code != 200:
                logger.warning(
                    "DeepSeek API returned %d for doc %s: %s",
                    resp.status_code,
                    doc.id,
                    resp.text[:500],
                )
                failures += 1
                continue
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            parsed = _parse_deepseek_response(raw)
            if parsed is None:
                logger.debug("Invalid or empty response for doc %s — skipping", doc.id)
                failures += 1
                continue
            pairs.append(parsed)

            # Track usage (prompt + completion tokens from API response)
            usage = data.get("usage", {})
            await record_usage_event(
                db,
                org_id=organization_id,
                api_key_id=None,
                pipeline_id=None,
                model=f"deepseek/{model}",
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                quota_reserved=settings.enforce_subscription_quotas,
            )
        except json.JSONDecodeError as exc:
            failures += 1
            logger.debug("JSON decode error for doc %s: %s — skipping", doc.id, exc)
        except (NoActiveSubscriptionError, QuotaExceededError):
            raise
        except Exception as exc:
            failures += 1
            logger.warning("DeepSeek call failed for doc %s: %s — skipping", doc.id, exc)

    if not pairs and failures:
        raise GoldenGenerationError("DeepSeek did not produce valid golden Q&A pairs")

    return pairs


async def save_golden_items(
    dataset_id: str,
    pairs: list[dict[str, str]],
    db: AsyncSession,
) -> list[DatasetGoldenItem]:
    """Persists golden Q&A pairs into dataset_golden_items table."""
    items = [
        DatasetGoldenItem(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            question=p["question"],
            answer=p["answer"],
        )
        for p in pairs
    ]
    db.add_all(items)
    await db.commit()
    for item in items:
        await db.refresh(item)
    return items
