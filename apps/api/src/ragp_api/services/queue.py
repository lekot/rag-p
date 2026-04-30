"""Unified enqueue helper with task envelope and idempotency.

Phase 1 of queue contract enforcement (PR 1 of 4).

All background work should go through ``enqueue()`` instead of calling
``pool.enqueue_job(...)`` directly.  This gives us:

- A consistent task envelope format ({task_id, task_type, tenant_id, ...}).
- Idempotency: identical ``idempotency_key`` values within a 24-hour window
  will return the original task_id without creating a duplicate ARQ job.
- A single place to add per-tenant fairness and backpressure in later PRs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ragp_api.settings import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Redis key prefix for idempotency SETNX locks.
_IDEM_PREFIX = "queue:idempotency:"
# TTL for idempotency keys (24 hours in seconds).
_IDEM_TTL = 86400

# Mapping from logical task_type to the ARQ function name registered in
# WorkerSettings.functions.  Add new task types here as they are introduced.
_TASK_TYPE_TO_ARQ_FUNCTION: dict[str, str] = {
    "experiment.run": "run_experiment_task",
    # Future task types will be added here when their workers are defined.
}


async def enqueue(
    *,
    task_type: str,
    tenant_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    queue_name: str | None = None,  # reserved for per-queue split (PR 2); ignored for now
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
        Reserved for the future worker-split PR.  Currently ignored; all
        jobs go to the default ARQ queue.
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

    task_id = str(uuid.uuid4())

    # --- Idempotency check via Redis SETNX ---
    if idempotency_key is not None:
        redis_key = f"{_IDEM_PREFIX}{idempotency_key}"

        # We need a plain Redis client (redis.asyncio) for SETNX, not the ARQ
        # pool.  Borrow the pool's connection if it exposes the low-level
        # client; otherwise open our own.
        import redis.asyncio as aioredis

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

    # --- Enqueue via ARQ ---
    own_pool = arq_pool is None
    pool: ArqRedis
    if own_pool:
        pool = await create_pool(RedisSettings(host=settings.redis_host, port=settings.redis_port))
    else:
        pool = arq_pool  # type: ignore[assignment]

    try:
        job = await pool.enqueue_job(arq_function, envelope=envelope)
        job_id: str | None = job.job_id if job is not None else None
    finally:
        if own_pool:
            await pool.aclose()

    logger.debug(
        "enqueue: task_type=%s task_id=%s job_id=%s",
        task_type,
        task_id,
        job_id,
    )

    return {
        "job_id": job_id,
        "task_id": task_id,
        "deduplicated": False,
    }
