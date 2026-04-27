"""ARQ WorkerSettings — entrypoint for the background worker process.

Run with:
    arq ragp_api.workers.main.WorkerSettings
"""

from __future__ import annotations

from arq.connections import RedisSettings

from ragp_api.settings import settings
from ragp_api.workers.tasks import run_experiment_task


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [run_experiment_task]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 5
    job_timeout = 600  # 10 minutes per experiment
