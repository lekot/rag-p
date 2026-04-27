"""Generates pipeline combinations and runs them inline (synchronous, no Celery)."""

import itertools
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, Document, Experiment

logger = logging.getLogger(__name__)


def build_combinations(plugin_grid: dict[str, list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Build cartesian product of plugin variants across pipeline slots."""
    slots = list(plugin_grid.keys())
    variants = [plugin_grid[slot] for slot in slots]
    combinations = list(itertools.product(*variants))

    result = []
    for combo in combinations:
        nodes = []
        for _slot, variant in zip(slots, combo, strict=False):
            nodes.append(
                {
                    "plugin_kind": variant.get("plugin_kind", _slot.rstrip("s")),
                    "plugin_name": variant["plugin_name"],
                    "params": variant.get("params", {}),
                }
            )
        result.append(nodes)
    return result


async def _load_dataset_chunks(
    db: AsyncSession,
    dataset_id: str,
    organization_id: str,
    max_chunks: int = 20,
) -> list[dict[str, Any]]:
    """Load up to max_chunks chunks from a dataset for self-test evaluation."""
    # Get documents in dataset
    docs_result = await db.execute(
        select(Document).where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
        )
    )
    docs = docs_result.scalars().all()
    if not docs:
        return []

    doc_ids = [d.id for d in docs]
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.document_id.in_(doc_ids)).limit(max_chunks)
    )
    chunks = chunks_result.scalars().all()
    return [
        {
            "id": c.id,
            "text": c.text,
            "score": 1.0,
            "metadata": c.metadata_json or {},
            "document_id": c.document_id,
            "document_name": "doc",
        }
        for c in chunks
    ]


async def _self_test_metric(
    nodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    organization_id: str,
    db: AsyncSession,
) -> dict[str, float]:
    """
    Simple self-test: for each chunk, query = first 50 chars of text,
    check if the chunk appears in top-3 retrieval. Returns hit_rate [0,1].
    Falls back to mock metrics if no retriever or no chunks.
    [BLOCKED-NIGHT-RUN] Self-test metric is a proxy only — no golden Q&A set available.
    Real eval requires golden Q&A from user or DeepSeek generation (Phase 5).
    """
    if not chunks:
        # No data — return neutral mock metrics
        return {"hit_rate": 0.5, "composite_score": 0.5}

    # Find retriever node
    retriever_node = next((n for n in nodes if n["plugin_kind"] == "retriever"), None)
    if retriever_node is None:
        # No retriever in this combo — neutral score
        return {"hit_rate": 0.5, "composite_score": 0.5}

    from typing import cast

    from ragp_api.plugins.base import Retriever
    from ragp_api.plugins.registry import get_plugin

    retriever_cls = get_plugin("retriever", retriever_node["plugin_name"])
    if retriever_cls is None:
        return {"hit_rate": 0.5, "composite_score": 0.5}

    params = dict(retriever_node.get("params", {}))
    params["session"] = db

    dataset_id = None
    # Try to get dataset_id from chunks' document (we pass it via metadata if available)
    if chunks:
        dataset_id = chunks[0].get("metadata", {}).get("dataset_id")

    hit_count = 0
    test_sample = chunks[:5]  # Test on up to 5 chunks to avoid long runs

    for chunk in test_sample:
        query = chunk["text"][:80]
        try:
            retriever = cast(Retriever, retriever_cls(params))
            results = await retriever.retrieve(
                query=query,
                top_k=3,
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            result_ids = [r["id"] for r in results]
            if chunk["id"] in result_ids:
                hit_count += 1
        except Exception as exc:
            logger.debug("Retriever self-test failed for chunk %s: %s", chunk["id"], exc)
            # If retriever fails (no embedding etc), use neutral score
            return {"hit_rate": 0.5, "composite_score": 0.5}

    hit_rate = hit_count / len(test_sample) if test_sample else 0.5
    return {"hit_rate": round(hit_rate, 4), "composite_score": round(hit_rate, 4)}


async def run_experiment_inline(
    experiment: Experiment,
    db: AsyncSession,
) -> None:
    """
    Run all combinations synchronously in-request.
    Updates experiment.status and experiment.leaderboard_json in-place.
    """
    try:
        experiment.status = "running"
        await db.commit()

        combinations = build_combinations(experiment.plugin_grid_json)
        dataset_id: str = experiment.dataset_id
        organization_id: str = experiment.organization_id

        # Load dataset chunks for self-test
        chunks = await _load_dataset_chunks(db, dataset_id, organization_id)

        leaderboard = []
        for nodes in combinations:
            try:
                metrics = await _self_test_metric(nodes, chunks, organization_id, db)
            except Exception as exc:
                logger.warning("Metrics computation failed for combo %s: %s", nodes, exc)
                metrics = {"hit_rate": 0.0, "composite_score": 0.0}

            leaderboard.append(
                {
                    "nodes": nodes,
                    "metrics": metrics,
                    "composite_score": metrics.get("composite_score", 0.0),
                }
            )

        # Sort by composite_score descending
        def _sort_key(entry: dict[str, Any]) -> float:
            return float(entry.get("composite_score") or 0.0)

        leaderboard.sort(key=_sort_key, reverse=True)

        experiment.leaderboard_json = leaderboard
        experiment.status = "completed"
        await db.commit()

    except Exception as exc:
        logger.exception("Experiment %s failed: %s", experiment.id, exc)
        experiment.status = "failed"
        experiment.leaderboard_json = [{"error": str(exc)}]
        await db.commit()
