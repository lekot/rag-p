"""Unified enqueue helper with task envelope, idempotency, and per-queue routing.

Phase 1–3 of queue contract enforcement:

- Phase 1: envelope + idempotency layer (PR #23).
- Phase 2: per-task-type queue routing (PR #25).
- Phase 3: per-tenant fairness via Redis sorted sets (this file).

Callers should always go through ``enqueue()`` instead of using
``pool.enqueue_job(...)`` directly.  This gives us:

- A consistent task envelope format ({task_id, task_type, tenant_id, ...}).
- Idempotency: identical ``idempotency_key`` values within a 24-hour window
  return the original task_id without creating a duplicate ARQ job.
- Automatic queue routing: each ``task_type`` maps to a single ARQ queue.
- Per-tenant fairness: one tenant cannot flood a queue and starve others.
  ``QuotaExceededError`` is raised when the cap is breached so callers can
  return HTTP 429 + Retry-After.
"""

from __future__ import annotations

import logging
import time
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

# Redis key prefix for per-tenant quota sorted sets.
_QUOTA_PREFIX = "tenant_quota:"

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


# Map queue name → per-tenant cap (None = no cap).
# Populated lazily from settings so tests can patch settings before import.
def _queue_caps() -> dict[str, int | None]:
    return {
        "rag.experiment": settings.queue_quota_experiment_per_tenant,
        "rag.ingest": settings.queue_quota_ingest_per_tenant,
        "rag.live": settings.queue_quota_live_per_tenant,
        "rag.maintenance": None,  # no cap
    }


class QuotaExceededError(Exception):
    """Raised when a tenant exceeds the per-queue enqueue rate limit."""

    def __init__(self, queue: str, tenant_id: str, retry_after_seconds: float) -> None:
        self.queue = queue
        self.tenant_id = tenant_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Tenant {tenant_id!r} exceeded quota for queue {queue!r}. "
            f"Retry after {retry_after_seconds:.1f}s."
        )


async def _check_tenant_quota(
    r: aioredis.Redis,
    tenant_id: str,
    queue_name: str,
    *,
    window_seconds: int | None = None,
    cap: int | None = None,
) -> None:
    """Enforce per-tenant sliding-window quota for *queue_name*.

    Sorted set ``tenant_quota:{queue_name}`` member = ``{tenant_id}:{uuid4}``,
    score = epoch ts of the enqueue.  Old entries outside the window are
    pruned before counting.  Raises ``QuotaExceededError`` when the per-tenant
    count >= cap.
    """
    if cap is None:
        caps = _queue_caps()
        cap = caps.get(queue_name)
    if cap is None:
        return  # No cap configured for this queue.

    if window_seconds is None:
        window_seconds = settings.queue_quota_window_seconds

    now = time.time()
    window_start = now - window_seconds
    redis_key = f"{_QUOTA_PREFIX}{queue_name}"

    await r.zremrangebyscore(redis_key, "-inf", window_start)

    tenant_prefix = f"{tenant_id}:"
    members: list[str] = await r.zrangebyscore(redis_key, window_start, "+inf")
    tenant_count = sum(1 for m in members if m.startswith(tenant_prefix))

    if tenant_count >= cap:
        tenant_members_with_scores: list[tuple[str, float]] = await r.zrangebyscore(
            redis_key, window_start, "+inf", withscores=True
        )
        tenant_scores = [
            score
            for member, score in tenant_members_with_scores
            if member.startswith(tenant_prefix)
        ]
        oldest_ts = min(tenant_scores) if tenant_scores else window_start
        retry_after = max(0.0, (oldest_ts + window_seconds) - now)
        logger.warning(
            "_check_tenant_quota: quota exceeded tenant=%s queue=%s count=%d cap=%d"
            " retry_after=%.1fs",
            tenant_id,
            queue_name,
            tenant_count,
            cap,
            retry_after,
        )
        raise QuotaExceededError(
            queue=queue_name, tenant_id=tenant_id, retry_after_seconds=retry_after
        )

    member = f"{tenant_id}:{uuid.uuid4()}"
    await r.zadd(redis_key, {member: now})
    await r.expire(redis_key, window_seconds * 2)


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
        Organisation / tenant identifier.  Stored in the envelope and used
        for per-tenant fairness.
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

    Raises
    ------
    QuotaExceededError
        When the tenant has exceeded the per-queue rate cap within the
        rolling window.
    ValueError
        When *task_type* is not registered.
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

    r: aioredis.Redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        # --- Per-tenant quota check (Phase 3) ---
        await _check_tenant_quota(r, tenant_id, resolved_queue)

        # --- Idempotency check via Redis SETNX ---
        if idempotency_key is not None:
            redis_key = f"{_IDEM_PREFIX}{idempotency_key}"
            was_set = await r.set(redis_key, task_id, nx=True, ex=_IDEM_TTL)
            if not was_set:
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

    envelope: dict[str, Any] = {
        "task_id": task_id,
        "task_type": task_type,
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "payload": payload,
        "ts": datetime.now(UTC).isoformat(),
    }

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
