"""Generates pipeline combinations and runs them inline (synchronous, no Celery)."""

import itertools
import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import Chunk, DatasetGoldenItem, Document, Experiment
from ragp_api.services.subscription import (
    NoActiveSubscriptionError,
    QuotaExceededError,
    consume_q,
    release_q,
)
from ragp_api.services.usage import record_usage_event

logger = logging.getLogger(__name__)

_SELF_TEST_SAMPLE_LIMIT = 5


def _metric_error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "error_code": code,
        "error": message,
        "composite_score": 0.0,
    }


async def _rechunk_documents_for_slot(
    db: AsyncSession,
    dataset_id: str,
    organization_id: str,
    plugin_name: str,
    params: dict[str, Any],
) -> None:
    """Re-chunk documents in a dataset if they were chunked with a different chunker.

    Compares ``plugin_name`` against each document's stored ``chunker_name``.
    Documents chunked with a different chunker (or not chunked at all) get their
    existing chunks deleted and re-chunked with the new chunker.
    """
    from typing import cast

    from ragp_api.plugins.base import Chunker
    from ragp_api.plugins.registry import get_plugin

    # Find docs that need re-chunking
    doc_result = await db.execute(
        select(Document).where(
            Document.dataset_id == dataset_id,
            Document.organization_id == organization_id,
            (Document.chunker_name != plugin_name) | (Document.chunker_name.is_(None)),
        )
    )
    docs_to_rechunk = list(doc_result.scalars().all())
    if not docs_to_rechunk:
        return

    chunker_cls = get_plugin("chunker", plugin_name)
    if chunker_cls is None:
        raise ValueError(f"Chunker plugin not found: {plugin_name}")
    chunker = cast(Chunker, chunker_cls(params))

    for doc in docs_to_rechunk:
        # Reconstruct text from existing chunks (order by chunk_index)
        existing = (
            (await db.execute(select(Chunk).where(Chunk.document_id == doc.id))).scalars().all()
        )
        if not existing:
            logger.warning("No existing chunks for doc %s, skipping re-chunk", doc.id)
            continue

        text = "\n\n".join(c.text for c in existing)

        # Delete existing chunks
        await db.execute(
            Chunk.__table__.delete().where(Chunk.document_id == doc.id)  # type: ignore[attr-defined]
        )

        # Chunk
        raw_chunks = await chunker.chunk(text)
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

        if chunk_objs:
            db.add_all(chunk_objs)

        doc.chunker_name = plugin_name
        doc.status = "indexed"

    await db.commit()


def build_combinations(plugin_grid: dict[str, list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Build cartesian product of plugin variants across pipeline slots."""
    slots = list(plugin_grid.keys())
    variants = [plugin_grid[slot] for slot in slots]
    combinations = list(itertools.product(*variants))

    result = []
    for combo in combinations:
        nodes = []
        for _slot, variant in zip(slots, combo, strict=False):
            plugin_name = variant.get("plugin_name") or variant.get("name")
            if not plugin_name:
                raise ValueError(f"Plugin variant in slot {_slot} has no plugin_name")
            nodes.append(
                {
                    "plugin_kind": variant.get("plugin_kind", _slot.rstrip("s")),
                    "plugin_name": plugin_name,
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


async def _load_golden_items(
    db: AsyncSession,
    dataset_id: str,
) -> list[DatasetGoldenItem]:
    """Load all golden Q&A items for a dataset."""
    result = await db.execute(
        select(DatasetGoldenItem).where(DatasetGoldenItem.dataset_id == dataset_id)
    )
    return list(result.scalars().all())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _golden_metrics(
    nodes: list[dict[str, Any]],
    golden_items: list[DatasetGoldenItem],
    organization_id: str,
    dataset_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Evaluate a pipeline combo against golden Q&A pairs.

    Metrics (no LLM-as-judge):
    - retrieval_hit: 1.0 if source_chunk_id in top-k retrieved chunks; 0.0 otherwise.
    - answer_similarity: cosine similarity embed(generated_answer) vs embed(expected_answer)
      (only when generator node present).
    - composite_score = 0.5*avg_hit + 0.5*avg_similarity  (or avg_hit when no generator).
    """
    from typing import cast

    from ragp_api.plugins.base import Embedder, Generator, Retriever
    from ragp_api.plugins.registry import get_plugin

    retriever_node = next((n for n in nodes if n["plugin_kind"] == "retriever"), None)
    generator_node = next((n for n in nodes if n["plugin_kind"] == "generator"), None)
    embedder_node = next((n for n in nodes if n["plugin_kind"] == "embedder"), None)

    if retriever_node is None:
        return _metric_error("missing_retriever", "Pipeline has no retriever node")

    retriever_cls = get_plugin("retriever", retriever_node["plugin_name"])
    if retriever_cls is None:
        return _metric_error(
            "unknown_retriever",
            f"Retriever plugin is not registered: {retriever_node['plugin_name']}",
        )

    retriever_params = dict(retriever_node.get("params", {}))
    retriever_params["session"] = db

    # Build embedder if available (for answer_similarity)
    embedder: Embedder | None = None
    if embedder_node is not None:
        embedder_cls = get_plugin("embedder", embedder_node["plugin_name"])
        if embedder_cls is not None:
            embedder = cast(Embedder, embedder_cls(dict(embedder_node.get("params", {}))))

    # Build generator if available
    generator: Generator | None = None
    if generator_node is not None:
        generator_cls = get_plugin("generator", generator_node["plugin_name"])
        if generator_cls is not None:
            generator = cast(Generator, generator_cls(dict(generator_node.get("params", {}))))

    hit_scores: list[float] = []
    sim_scores: list[float] = []
    retrieval_failures = 0

    for item in golden_items:
        query = item.question

        # Embed query — if embedder fails, fall back to BM25-only
        query_vec: list[float] | None = None
        if embedder is not None:
            try:
                query_vec = (await embedder.embed([query]))[0]
            except Exception:
                query_vec = None  # BM25-only fallback

        # Retrieve (BM25 if no query_vec, hybrid otherwise)
        try:
            retriever = cast(Retriever, retriever_cls(retriever_params))
            results = await retriever.retrieve(
                query=query,
                top_k=5,
                organization_id=organization_id,
                dataset_id=dataset_id,
                query_vec=query_vec,
            )
        except Exception as exc:
            logger.warning("Retriever failed for golden item %s: %s", item.id, exc)
            retrieval_failures += 1
            hit_scores.append(0.0)
            continue

        # Retrieval hit
        result_ids = [r["id"] for r in results]
        hit = 1.0 if item.source_chunk_id and item.source_chunk_id in result_ids else 0.0
        hit_scores.append(hit)

        # Answer similarity — only when both generator and embedder are available
        if generator is not None and embedder is not None:
            try:
                gen_result = await generator.generate(query=query, contexts=results)
                generated_answer = gen_result.get("answer", "")
                vecs = await embedder.embed([generated_answer, item.answer])
                sim = _cosine_similarity(vecs[0], vecs[1])
                sim_scores.append(sim)
            except Exception as exc:
                logger.debug("Answer similarity failed for golden item %s: %s", item.id, exc)

    if not hit_scores:
        return _metric_error("no_golden_scores", "Golden evaluation produced no scores")

    avg_hit = sum(hit_scores) / len(hit_scores)
    avg_sim = sum(sim_scores) / len(sim_scores) if sim_scores else None
    composite = 0.5 * avg_hit + 0.5 * avg_sim if avg_sim is not None else avg_hit

    metrics: dict[str, Any] = {
        "status": "completed",
        "retrieval_hit": round(avg_hit, 4),
        "context_recall": round(avg_hit, 4),
        "composite_score": round(composite, 4),
    }
    if avg_sim is not None:
        metrics["answer_similarity"] = round(avg_sim, 4)
        metrics["answer_relevance"] = round(avg_sim, 4)
    if retrieval_failures:
        metrics["warning"] = f"{retrieval_failures} golden item(s) failed during retrieval"
    return metrics


async def _self_test_metric(
    nodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    organization_id: str,
    dataset_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Simple self-test: for each chunk, query = first 50 chars of text,
    check if the chunk appears in top-3 retrieval. Returns hit_rate [0,1].
    Returns explicit failed/skipped metrics instead of a neutral placeholder.
    [BLOCKED-NIGHT-RUN] Self-test metric is a proxy only — no golden Q&A set available.
    Real eval requires golden Q&A from user or DeepSeek generation (Phase 5).
    """
    if not chunks:
        return _metric_error("no_dataset_chunks", "Dataset has no chunks to evaluate")

    # Find retriever node
    retriever_node = next((n for n in nodes if n["plugin_kind"] == "retriever"), None)
    if retriever_node is None:
        return _metric_error("missing_retriever", "Pipeline has no retriever node")
    embedder_node = next((n for n in nodes if n["plugin_kind"] == "embedder"), None)

    from typing import cast

    from ragp_api.plugins.base import Embedder, Retriever
    from ragp_api.plugins.registry import get_plugin

    retriever_cls = get_plugin("retriever", retriever_node["plugin_name"])
    if retriever_cls is None:
        return _metric_error(
            "unknown_retriever",
            f"Retriever plugin is not registered: {retriever_node['plugin_name']}",
        )

    params = dict(retriever_node.get("params", {}))
    params["session"] = db

    embedder: Embedder | None = None
    if embedder_node is not None:
        embedder_cls = get_plugin("embedder", embedder_node["plugin_name"])
        if embedder_cls is None:
            return _metric_error(
                "unknown_embedder",
                f"Embedder plugin is not registered: {embedder_node['plugin_name']}",
            )
        embedder = cast(Embedder, embedder_cls(dict(embedder_node.get("params", {}))))

    hit_count = 0
    attempted = 0
    failures = 0
    test_sample = chunks[:_SELF_TEST_SAMPLE_LIMIT]  # Test on a bounded sample to avoid long runs

    for chunk in test_sample:
        query = chunk["text"][:80]

        # Embed query — if embedder fails, fall back to BM25-only
        query_vec: list[float] | None = None
        if embedder is not None:
            try:
                query_vec = (await embedder.embed([query]))[0]
            except Exception:
                query_vec = None  # BM25-only fallback

        # Retrieve (BM25 if no query_vec, hybrid otherwise)
        try:
            retriever = cast(Retriever, retriever_cls(params))
            results = await retriever.retrieve(
                query=query,
                top_k=3,
                organization_id=organization_id,
                dataset_id=dataset_id,
                query_vec=query_vec,
            )
            attempted += 1
            result_ids = [r["id"] for r in results]
            if chunk["id"] in result_ids:
                hit_count += 1
        except Exception as exc:
            logger.warning("Retriever self-test failed for chunk %s: %s", chunk["id"], exc)
            failures += 1

    if attempted == 0:
        return _metric_error(
            "retriever_failed",
            f"Retriever failed for all sampled chunks ({failures}/{len(test_sample)})",
        )

    hit_rate = hit_count / attempted
    metrics: dict[str, Any] = {
        "status": "completed",
        "hit_rate": round(hit_rate, 4),
        "context_recall": round(hit_rate, 4),
        "composite_score": round(hit_rate, 4),
    }
    if failures:
        metrics["warning"] = f"{failures} sampled chunk(s) failed during retrieval"
    return metrics


async def run_experiment_inline(
    experiment: Experiment,
    db: AsyncSession,
) -> None:
    """
    Run all combinations synchronously in-request.
    Updates experiment.status and experiment.leaderboard_json in-place.

    If the dataset has golden Q&A items, uses retrieval_hit + answer_similarity metrics.
    Otherwise falls back to self-test hit-rate heuristic.
    """
    reserved_units = 0

    def _touch() -> None:
        # Watchdog heartbeat — bumped before every commit so the stale-experiment
        # cron can distinguish a live worker (slow combo) from a dead one.
        experiment.updated_at = datetime.now(UTC)

    try:
        experiment.status = "running"
        _touch()
        await db.commit()

        combinations = build_combinations(experiment.plugin_grid_json)
        dataset_id: str = experiment.dataset_id
        organization_id: str = experiment.organization_id

        # Re-chunk documents if the pipeline uses a different chunker than
        # the one that was used at upload time.  Uses the first pipeline
        # combo's chunker as the reference (all combos share the same slot).
        if combinations and "chunkers" in experiment.plugin_grid_json:
            first_chunker = experiment.plugin_grid_json["chunkers"][0]
            # Re-chunking deletes old chunks, which would set source_chunk_id
            # to NULL on all golden items via ON DELETE SET NULL, invalidating
            # every hit.  Delete golden items together with their chunks.
            await db.execute(
                delete(DatasetGoldenItem).where(DatasetGoldenItem.dataset_id == dataset_id)
            )
            await _rechunk_documents_for_slot(
                db,
                dataset_id=dataset_id,
                organization_id=organization_id,
                plugin_name=first_chunker["plugin_name"],
                params=first_chunker.get("params", {}),
            )
            _touch()
            await db.commit()

        # Check whether golden Q&A exists for this dataset
        # Golden items whose source_chunk_id is NULL are orphaned (chunks were
        # deleted by re-chunking or document removal).  Filter them out so the
        # experiment falls back to self-test instead of always hitting 0.0.
        # Also clean them up from the DB so the list doesn't grow stale.
        await db.execute(
            delete(DatasetGoldenItem).where(
                DatasetGoldenItem.dataset_id == dataset_id,
                DatasetGoldenItem.source_chunk_id.is_(None),
            )
        )
        golden_items = await _load_golden_items(db, dataset_id)
        use_golden = len(golden_items) > 0

        # Load dataset chunks for self-test fallback (only needed when no golden)
        chunks: list[dict[str, Any]] = []
        if not use_golden:
            chunks = await _load_dataset_chunks(db, dataset_id, organization_id)

        units_per_combo = (
            len(golden_items) if use_golden else min(len(chunks), _SELF_TEST_SAMPLE_LIMIT)
        )
        reserved_units = max(1, len(combinations) * max(1, units_per_combo))
        try:
            await consume_q(db, organization_id, count=reserved_units)
            _touch()
            await db.commit()
        except NoActiveSubscriptionError:
            experiment.status = "failed"
            experiment.leaderboard_json = [
                {
                    "error_code": "no_active_plan",
                    "error": "Активной подписки нет. Купите план на /pricing",
                }
            ]
            _touch()
            await db.commit()
            return
        except QuotaExceededError as exc:
            experiment.status = "failed"
            experiment.leaderboard_json = [
                {
                    "error_code": "quota_exceeded",
                    "error": "Лимит RAG-запросов исчерпан. Перейдите на старший тариф.",
                    "q_used": exc.q_used,
                    "q_limit": exc.q_limit,
                }
            ]
            _touch()
            await db.commit()
            return

        leaderboard = []
        for nodes in combinations:
            try:
                if use_golden:
                    metrics = await _golden_metrics(
                        nodes, golden_items, organization_id, dataset_id, db
                    )
                else:
                    metrics = await _self_test_metric(
                        nodes, chunks, organization_id, dataset_id, db
                    )
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
            # Heartbeat after each combo so a slow grid does not look stale.
            _touch()
            await db.commit()

        # Sort by composite_score descending
        def _sort_key(entry: dict[str, Any]) -> float:
            return float(entry.get("composite_score") or 0.0)

        leaderboard.sort(key=_sort_key, reverse=True)

        experiment.leaderboard_json = leaderboard
        experiment.status = "completed"
        _touch()
        await db.commit()
        await record_usage_event(
            db,
            org_id=organization_id,
            api_key_id=None,
            pipeline_id=None,
            model="experiment",
            prompt_tokens=0,
            completion_tokens=0,
            quota_reserved=True,
        )

    except Exception as exc:
        logger.exception("Experiment %s failed: %s", experiment.id, exc)
        if reserved_units:
            await release_q(db, experiment.organization_id, count=reserved_units)
        experiment.status = "failed"
        experiment.leaderboard_json = [{"error": str(exc)}]
        _touch()
        await db.commit()
