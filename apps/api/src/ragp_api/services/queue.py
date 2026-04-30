"""Unified enqueue helper with task envelope, idempotency, and per-queue routing.

Phase 1 introduced the envelope + idempotency layer.
Phase 2 adds per-task-type queue routing so ``enqueue()`` automatically picks
the right ARQ queue (``rag.experiment``, ``rag.ingest``, …).

Callers should always go through ``enqueue()`` instead of using
``pool.enqueue_job(...)`` directly.  This gives us:

- A consistent task envelope format ({task_id, task_type, tenant_id, ...}).
- Idempotency: identical ``idempotency_key`` values within a 24-hour window
  return the original task_id without creating a duplicate ARQ job.
- Automatic queue routing: each ``task_type`` maps to a single ARQ queue.
- A single place to add per-tenant fairness and backpressure in later PRs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ragp_api.settings import settings

logger = logging.getLogger(__name__)

# Redis key prefix for idempotency SETNX locks.
_IDEM_PREFIX = "queue:idempotency:"
# TTL for idempotency keys (24 hours in seconds).
_IDEM_TTL = 86400

# Mapping from logical task_type to the ARQ function name registered in
# WorkerSettings.functions.  Add new task types here as they are introduced.
_TASK_TYPE_TO_ARQ_FUNCTION: dict[str, str] = {
    "experiment.run": "run_experiment_task",
    "dataset.ingest": "run_dataset_ingest_task",
}

# Maps every known task_type to its ARQ queue name.
# Extend this dict when a new task_type is introduced — never hard-code the
# queue name at the call site.
_TASK_TYPE_TO_QUEUE: dict[str, str] = {
    "experiment.run": "rag.experiment",
    "dataset.ingest": "rag.ingest",
}


async def enqueue(
    *,
    task_type: str,
    tenant_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    queue_name: str | None = None,
    arq_pool: ArqRedis | None = None,
) -> dict[str, Any]:
    """Enqueue a background task using a unified task envelope.

    Parameters
    ----------
    task_type:
        Logical task identifier (e.g. ``"experiment.run"``).  Must be a key
        in ``_TASK_TYPE_TO_ARQ_FUNCTION``.
    tenant_id:
        Organisation / tenant identifier.  Stored in the envelope for
        observability and future per-tenant fairness (PR 3).
    payload:
        Arbitrary task-specific data.  Passed as-is inside the envelope.
    idempotency_key:
        Optional deduplication key.  When provided, a second call with the
        same key within 24 hours returns the original result without
        submitting a new ARQ job.
    queue_name:
        Override the queue resolved from ``_TASK_TYPE_TO_QUEUE``.  Leave
        ``None`` so that routing stays driven by the task_type table.
    arq_pool:
        An existing ``ArqRedis`` pool to reuse.  When *None* a temporary
        pool is created and closed after the call.

    Returns
    -------
    dict with keys:
        - ``job_id`` (str | None): ARQ job identifier; *None* for deduplicated calls.
        - ``task_id`` (str): UUID for this logical task (stable across deduplication).
        - ``deduplicated`` (bool): *True* when the idempotency key was already set.
    """
    arq_function = _TASK_TYPE_TO_ARQ_FUNCTION.get(task_type)
    if arq_function is None:
        raise ValueError(
            f"Unknown task_type {task_type!r}.  "
            f"Register it in services/queue._TASK_TYPE_TO_ARQ_FUNCTION."
        )

    resolved_queue = queue_name or _TASK_TYPE_TO_QUEUE.get(task_type)
    if resolved_queue is None:
        raise ValueError(
            f"No queue registered for task_type {task_type!r} — add it to "
            "_TASK_TYPE_TO_QUEUE in services/queue.py"
        )

    task_id = str(uuid.uuid4())

    # --- Idempotency check via Redis SETNX ---
    if idempotency_key is not None:
        redis_key = f"{_IDEM_PREFIX}{idempotency_key}"

        # We need a plain Redis client (redis.asyncio) for SETNX, not the ARQ
        # pool.
        r: aioredis.Redis = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            # SETNX + EXPIRE atomically via SET … NX EX
            was_set = await r.set(redis_key, task_id, nx=True, ex=_IDEM_TTL)
            if not was_set:
                # Key already exists — fetch the original task_id
                existing_task_id = await r.get(redis_key)
                logger.debug(
                    "enqueue: deduplicated task_type=%s idempotency_key=%s existing_task_id=%s",
                    task_type,
                    idempotency_key,
                    existing_task_id,
                )
                return {
                    "job_id": None,
                    "task_id": existing_task_id or task_id,
                    "deduplicated": True,
                }
        finally:
            await r.aclose()

    # --- Build envelope ---
    envelope: dict[str, Any] = {
        "task_id": task_id,
        "task_type": task_type,
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "payload": payload,
        "ts": datetime.now(UTC).isoformat(),
    }

    # --- Enqueue via ARQ on the resolved queue ---
    own_pool = arq_pool is None
    pool: ArqRedis
    if own_pool:
        pool = await create_pool(RedisSettings(host=settings.redis_host, port=settings.redis_port))
    else:
        pool = arq_pool  # type: ignore[assignment]

    try:
        job = await pool.enqueue_job(
            arq_function,
            envelope=envelope,
            _queue_name=resolved_queue,
        )
        job_id: str | None = job.job_id if job is not None else None
    finally:
        if own_pool:
            await pool.aclose()

    logger.debug(
        "enqueue: task_type=%s queue=%s task_id=%s job_id=%s",
        task_type,
        resolved_queue,
        task_id,
        job_id,
    )

    return {
        "job_id": job_id,
        "task_id": task_id,
        "deduplicated": False,
    }
