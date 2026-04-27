"""Generates golden Q&A pairs by sampling chunks from a dataset via DeepSeek."""

import json
import logging
import uuid
from typing import cast

import litellm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, DatasetGoldenItem, Document

logger = logging.getLogger(__name__)

_QA_PROMPT = (
    "Read the following text chunk and generate ONE concise question that this chunk answers, "
    "plus the exact answer.\n"
    'Return JSON: {{"question": "...", "answer": "..."}}.\n'
    "No explanations.\n\n"
    "Chunk:\n{chunk_text}"
)


async def generate_golden_qa(
    dataset_id: str,
    organization_id: str,
    db: AsyncSession,
    sample_size: int = 10,
    model: str = "deepseek/deepseek-v4-flash",
) -> list[dict[str, str]]:
    """Generates a list of golden Q&A pairs by sampling chunks from the dataset.

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

    pairs: list[dict[str, str]] = []
    for chunk in chunks:
        prompt = _QA_PROMPT.format(chunk_text=chunk.text)
        try:
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            raw = cast(str, response.choices[0].message.content) or ""
            # Strip markdown code fences if present
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
                logger.debug("Empty question/answer for chunk %s — skipping", chunk.id)
                continue
            pairs.append(
                {
                    "question": question,
                    "answer": answer,
                    "source_chunk_id": chunk.id,
                }
            )
        except json.JSONDecodeError as exc:
            logger.debug("JSON parse error for chunk %s: %s — skipping", chunk.id, exc)
        except Exception as exc:
            logger.warning("LLM call failed for chunk %s: %s — skipping", chunk.id, exc)

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
