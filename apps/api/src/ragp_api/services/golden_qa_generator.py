"""Generates golden Q&A pairs by sampling chunks from a dataset via DeepSeek API."""

import json
import logging
import uuid

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, DatasetGoldenItem, Document
from ragp_api.settings import settings

logger = logging.getLogger(__name__)

_QA_PROMPT = (
    "Read the following text chunk and generate ONE concise question that this chunk answers, "
    "plus the exact answer.\n"
    'Return JSON: {{"question": "...", "answer": "..."}}.\n'
    "No explanations.\n\n"
    "Chunk:\n{chunk_text}"
)


class GoldenGenerationError(RuntimeError):
    """Raised when chunks exist but the LLM cannot produce any golden Q&A pairs."""


def _extractive_pair(chunk: Chunk) -> dict[str, str]:
    text = " ".join(chunk.text.split())
    answer = text[:700].rstrip()
    if len(text) > 700:
        answer += "..."
    return {
        "question": "Какая информация содержится в этом фрагменте?",
        "answer": answer,
        "source_chunk_id": chunk.id,
    }


def _parse_deepseek_response(raw: str, chunk_id: str) -> dict[str, str] | None:
    """Parse DeepSeek JSON response, stripping markdown fences if present.

    Returns {"question": ..., "answer": ..., "source_chunk_id": ...} or None.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    parsed = json.loads(raw)
    question = str(parsed.get("question", "")).strip()
    answer = str(parsed.get("answer", "")).strip()
    if not question or not answer:
        return None
    return {"question": question, "answer": answer, "source_chunk_id": chunk_id}


async def _call_deepseek(
    url: str,
    headers: dict[str, str],
    body: dict[str, str | int | float | list[dict[str, str]]],
) -> httpx.Response:
    """Single DeepSeek API call — isolated for testability."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await client.post(url, json=body, headers=headers)


async def generate_golden_qa(
    dataset_id: str,
    organization_id: str,
    db: AsyncSession,
    sample_size: int = 10,
    model: str = "deepseek-v4-flash",
) -> list[dict[str, str]]:
    """Generates a list of golden Q&A pairs by sampling chunks from the dataset.

    Calls DeepSeek API directly via httpx (bypasses litellm for transparency).
    Returns list of {"question": str, "answer": str, "source_chunk_id": str}.
    """
    # Sample random chunks from the dataset via JOIN with documents
    # SQLite (test env) does not support RANDOM() as a function name but does support it as
    # ORDER BY RANDOM().  PostgreSQL also supports ORDER BY RANDOM().
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.dataset_id == dataset_id, Document.organization_id == organization_id)
        .order_by(func.random())
        .limit(sample_size)
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()

    if not chunks:
        logger.info("No chunks found for dataset %s — returning empty golden set", dataset_id)
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
    for chunk in chunks:
        prompt = _QA_PROMPT.format(chunk_text=chunk.text)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2000,
        }
        try:
            resp = await _call_deepseek(url, headers, body)
            if resp.status_code != 200:
                logger.warning(
                    "DeepSeek API returned %d for chunk %s: %s",
                    resp.status_code,
                    chunk.id,
                    resp.text[:500],
                )
                failures += 1
                if settings.llm_fallback_mode == "extractive":
                    pairs.append(_extractive_pair(chunk))
                continue
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            parsed = _parse_deepseek_response(raw, chunk.id)
            if parsed is None:
                logger.debug("Empty question/answer for chunk %s — skipping", chunk.id)
                continue
            pairs.append(parsed)
        except json.JSONDecodeError as exc:
            failures += 1
            logger.debug("JSON parse error for chunk %s: %s — skipping", chunk.id, exc)
            if settings.llm_fallback_mode == "extractive":
                pairs.append(_extractive_pair(chunk))
        except httpx.HTTPError as exc:
            failures += 1
            logger.warning("HTTP error for chunk %s: %s — skipping", chunk.id, exc)
            if settings.llm_fallback_mode == "extractive":
                pairs.append(_extractive_pair(chunk))

    if not pairs and failures:
        raise GoldenGenerationError("LLM did not generate valid golden Q&A pairs")

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
            source_chunk_id=p.get("source_chunk_id"),
        )
        for p in pairs
    ]
    db.add_all(items)
    await db.commit()
    for item in items:
        await db.refresh(item)
    return items
