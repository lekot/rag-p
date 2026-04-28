"""ARQ WorkerSettings — entrypoint for the background worker process.

Run with:
    arq ragp_api.workers.main.WorkerSettings
"""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron
from prometheus_client import Counter, Histogram, start_http_server

from ragp_api.settings import settings
from ragp_api.workers.tasks import aggregate_usage_daily, run_experiment_task

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


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [run_experiment_task, aggregate_usage_daily]
    cron_jobs = [
        cron(aggregate_usage_daily, hour=1, minute=0, run_at_startup=False),
    ]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 5
    job_timeout = 600  # 10 minutes per experiment
    on_startup = on_startup
    on_job_start = on_job_start
    on_job_complete = on_job_complete
