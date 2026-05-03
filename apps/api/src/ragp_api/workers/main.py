"""ARQ WorkerSettings — entrypoints for per-queue worker processes.

Phase 2 of 4: split workers per queue (live / ingest / experiment / maintenance).

Each class is a separate ARQ worker entrypoint.  Run with, e.g.:
    arq ragp_api.workers.main.WorkerExperimentSettings
    arq ragp_api.workers.main.WorkerIngestSettings
    arq ragp_api.workers.main.WorkerMaintenanceSettings

``WorkerSettings`` is kept as a backwards-compatibility alias for
``WorkerExperimentSettings`` so that any existing ``docker compose`` or
deployment script that references the old name continues to work during the
first rollout.  New deployments should use the per-queue class names.

Notes on score tasks
--------------------
There are currently no dedicated score task functions in the codebase.
``WorkerExperimentSettings`` therefore handles both experiment orchestration
and any future scoring sub-tasks (they would share ``rag.experiment`` queue).
A separate ``WorkerScoreSettings`` / ``rag.score`` queue can be split off in a
later PR once scoring tasks exist.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron
from prometheus_client import Counter, Histogram, start_http_server

from ragp_api.settings import settings
from ragp_api.workers.tasks import (
    aggregate_usage_daily,
    chunk_document,
    expire_subscriptions_task,
    mark_experiment_failed_on_crash,
    mark_stale_experiments_failed,
    notify_subscription_lifecycle_task,
    run_experiment_task,
)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

jobs_total = Counter(
    "ragp_worker_jobs_total",
    "Total number of worker jobs processed",
    ["status"],
)

job_duration_seconds = Histogram(
    "ragp_worker_job_duration_seconds",
    "Worker job execution duration in seconds",
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)


async def on_startup(ctx: dict) -> None:  # type: ignore[type-arg]
    """Start Prometheus metrics HTTP server on worker startup."""
    start_http_server(9090, addr="0.0.0.0")


async def on_job_start(ctx: dict) -> None:  # type: ignore[type-arg]
    """Record job start time for duration tracking."""
    import time

    ctx["_job_start"] = time.monotonic()


async def on_job_complete(ctx: dict) -> None:  # type: ignore[type-arg]
    """Record job completion metrics."""
    import time

    duration = time.monotonic() - ctx.get("_job_start", time.monotonic())
    job_duration_seconds.observe(duration)

    # ARQ sets ctx["job_try"] and result info; success = no exception stored
    success = ctx.get("result_error") is None
    jobs_total.labels(status="completed" if success else "failed").inc()


async def on_job_failure(ctx: dict) -> None:  # type: ignore[type-arg]
    """ARQ ``after_job_end`` hook for hard worker failures (timeout/crash).

    ARQ invokes this when a job finishes with an exception.  For
    ``run_experiment_task`` we synthesise a ``failed`` row with
    ``error_code='worker_crash'`` so the experiment never gets stuck in
    queued/running.  Wrapped in a broad try/except — the callback itself must
    never raise.

    Supports both the legacy positional-arg calling convention and the new
    envelope-based convention introduced in services/queue.py (PR 1).
    """
    try:
        function_name = ctx.get("function") or ctx.get("function_name")
        if function_name != "run_experiment_task":
            return

        # New convention: experiment_id is inside kwargs["envelope"]["payload"]
        kwargs = ctx.get("kwargs") or {}
        envelope = kwargs.get("envelope") or {}
        experiment_id: str | None = (
            envelope.get("payload", {}).get("experiment_id") if envelope else None
        )

        # Legacy fallback: experiment_id was the first positional arg
        if not experiment_id:
            args = ctx.get("args") or ()
            experiment_id = args[0] if args else None

        if not experiment_id:
            return

        exc = ctx.get("exception") or ctx.get("result")
        error_msg = str(exc) if exc is not None else "Unknown worker failure"

        await mark_experiment_failed_on_crash(experiment_id, error_msg)
    except Exception as exc:  # pragma: no cover — defensive guard
        import logging

        logging.getLogger(__name__).exception("on_job_failure callback itself failed: %s", exc)


# ---------------------------------------------------------------------------
# Shared Redis settings helper
# ---------------------------------------------------------------------------


def _redis_settings() -> RedisSettings:
    return RedisSettings(host=settings.redis_host, port=settings.redis_port)


# ---------------------------------------------------------------------------
# Worker: rag.live — synchronous user-facing queries (reserved for future use)
# ---------------------------------------------------------------------------


class WorkerLiveSettings:
    """ARQ worker for the ``rag.live`` queue.

    No functions are registered yet — this queue is reserved for future
    low-latency synchronous user requests that must not compete with
    long-running ingest or experiment jobs.
    """

    queue_name = "rag.live"
    functions: list[Any] = []
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 30
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_end = on_job_complete


# ---------------------------------------------------------------------------
# Worker: rag.ingest — long-running dataset upload / ingestion jobs
# ---------------------------------------------------------------------------


class WorkerIngestSettings:
    """ARQ worker for the ``rag.ingest`` queue.

    Handles async document chunking + embedding after file upload.
    """

    queue_name = "rag.ingest"
    functions: list[Any] = [chunk_document]
    redis_settings = _redis_settings()
    max_jobs = 2
    job_timeout = 1800  # 30 minutes — large file uploads can be slow
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_end = on_job_complete


# ---------------------------------------------------------------------------
# Worker: rag.experiment — eval grid runs (+ score sub-tasks until split)
# ---------------------------------------------------------------------------


class WorkerExperimentSettings:
    """ARQ worker for the ``rag.experiment`` queue.

    Handles experiment orchestration.  Score sub-tasks share this queue for
    now; a dedicated ``rag.score`` queue/worker can be split off later.
    """

    queue_name = "rag.experiment"
    functions = [run_experiment_task]
    redis_settings = _redis_settings()
    max_jobs = 1
    job_timeout = 600  # 10 minutes per experiment
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_end = on_job_complete
    after_job_end = on_job_failure


# ---------------------------------------------------------------------------
# Worker: rag.maintenance — cron jobs only
# ---------------------------------------------------------------------------


class WorkerMaintenanceSettings:
    """ARQ worker for the ``rag.maintenance`` queue.

    Runs periodic housekeeping cron jobs.  No ad-hoc enqueueable functions
    are registered — only the cron schedule matters here.
    """

    queue_name = "rag.maintenance"
    functions = [
        aggregate_usage_daily,
        expire_subscriptions_task,
        mark_stale_experiments_failed,
        notify_subscription_lifecycle_task,
    ]
    cron_jobs = [
        cron(aggregate_usage_daily, hour=1, minute=0, run_at_startup=False),
        # Daily: expire subscriptions whose period has ended.
        cron(expire_subscriptions_task, hour=0, minute=10, run_at_startup=False),
        # Daily: notify org owners about upcoming/just-passed subscription expiry.
        # Runs at 00:30 UTC, after expire_subscriptions_task has flipped any
        # past-due rows to status=expired.
        cron(notify_subscription_lifecycle_task, hour=0, minute=30, run_at_startup=False),
        # Watchdog: scan for queued/running experiments whose heartbeat went
        # stale and mark them failed.  Runs every two minutes.
        cron(
            mark_stale_experiments_failed,
            minute=set(range(0, 60, 2)),
            run_at_startup=False,
        ),
    ]
    redis_settings = _redis_settings()
    max_jobs = 2
    job_timeout = 300
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_end = on_job_complete


# ---------------------------------------------------------------------------
# Backwards-compatibility alias
# ---------------------------------------------------------------------------

#: ``WorkerSettings`` is kept so that any existing deployment script that
#: runs ``arq ragp_api.workers.main.WorkerSettings`` keeps working without
#: change during a rolling rollout.  Prefer ``WorkerExperimentSettings`` for
#: new deployments.
WorkerSettings = WorkerExperimentSettings
