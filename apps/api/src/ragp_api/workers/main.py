"""ARQ WorkerSettings — entrypoint for the background worker process.

Run with:
    arq ragp_api.workers.main.WorkerSettings
"""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron
from prometheus_client import Counter, Histogram, start_http_server

from ragp_api.settings import settings
from ragp_api.workers.tasks import (
    aggregate_usage_daily,
    expire_subscriptions_task,
    mark_experiment_failed_on_crash,
    mark_stale_experiments_failed,
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


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [run_experiment_task, aggregate_usage_daily, mark_stale_experiments_failed]
    cron_jobs = [
        cron(aggregate_usage_daily, hour=1, minute=0, run_at_startup=False),
        # Daily: expire subscriptions whose period has ended
        cron(expire_subscriptions_task, hour=0, minute=10, run_at_startup=False),
        # Watchdog: scan for queued/running experiments whose heartbeat went
        # stale and mark them failed.  Runs every two minutes.
        cron(
            mark_stale_experiments_failed,
            minute=set(range(0, 60, 2)),
            run_at_startup=False,
        ),
    ]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 5
    job_timeout = 600  # 10 minutes per experiment
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_end = on_job_complete
    after_job_end = on_job_failure
