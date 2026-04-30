"""Tests for Phase 2: per-queue worker split and queue routing.

Verifies:
- WorkerExperimentSettings.queue_name == "rag.experiment" and includes run_experiment_task.
- WorkerIngestSettings.queue_name == "rag.ingest".
- WorkerMaintenanceSettings.queue_name == "rag.maintenance" and includes cron tasks.
- WorkerSettings is a backwards-compat alias for WorkerExperimentSettings.
- enqueue("experiment.run", ...) calls pool.enqueue_job with _queue_name="rag.experiment".
- enqueue("dataset.ingest", ...) calls pool.enqueue_job with _queue_name="rag.ingest".
- enqueue() raises ValueError for an unknown task_type.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# WorkerSettings class structure
# ---------------------------------------------------------------------------


def test_worker_experiment_queue_name():
    from ragp_api.workers.main import WorkerExperimentSettings

    assert WorkerExperimentSettings.queue_name == "rag.experiment"


def test_worker_experiment_contains_run_experiment_task():
    from ragp_api.workers.main import WorkerExperimentSettings
    from ragp_api.workers.tasks import run_experiment_task

    assert run_experiment_task in WorkerExperimentSettings.functions


def test_worker_experiment_max_jobs():
    from ragp_api.workers.main import WorkerExperimentSettings

    assert WorkerExperimentSettings.max_jobs == 1


def test_worker_ingest_queue_name():
    from ragp_api.workers.main import WorkerIngestSettings

    assert WorkerIngestSettings.queue_name == "rag.ingest"


def test_worker_ingest_max_jobs():
    from ragp_api.workers.main import WorkerIngestSettings

    assert WorkerIngestSettings.max_jobs == 2


def test_worker_maintenance_queue_name():
    from ragp_api.workers.main import WorkerMaintenanceSettings

    assert WorkerMaintenanceSettings.queue_name == "rag.maintenance"


def test_worker_maintenance_has_cron_jobs():
    from ragp_api.workers.main import WorkerMaintenanceSettings

    assert len(WorkerMaintenanceSettings.cron_jobs) >= 3


def test_worker_maintenance_functions_include_cron_tasks():
    from ragp_api.workers.main import WorkerMaintenanceSettings
    from ragp_api.workers.tasks import (
        aggregate_usage_daily,
        expire_subscriptions_task,
        mark_stale_experiments_failed,
    )

    funcs = WorkerMaintenanceSettings.functions
    assert aggregate_usage_daily in funcs
    assert expire_subscriptions_task in funcs
    assert mark_stale_experiments_failed in funcs


def test_worker_live_queue_name():
    from ragp_api.workers.main import WorkerLiveSettings

    assert WorkerLiveSettings.queue_name == "rag.live"


def test_worker_settings_is_alias_for_experiment():
    """WorkerSettings must remain a backwards-compat alias."""
    from ragp_api.workers.main import WorkerExperimentSettings, WorkerSettings

    assert WorkerSettings is WorkerExperimentSettings


# ---------------------------------------------------------------------------
# enqueue() routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_experiment_run_routes_to_experiment_queue():
    """enqueue(task_type="experiment.run") must pass _queue_name="rag.experiment"."""
    from ragp_api.services.queue import enqueue

    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j1"))

    await enqueue(
        task_type="experiment.run",
        tenant_id="org-1",
        payload={"experiment_id": "exp-123"},
        arq_pool=pool,
    )

    pool.enqueue_job.assert_awaited_once()
    kwargs = pool.enqueue_job.call_args.kwargs
    assert pool.enqueue_job.call_args.args[0] == "run_experiment_task"
    assert kwargs["_queue_name"] == "rag.experiment"
    assert kwargs["envelope"]["task_type"] == "experiment.run"


@pytest.mark.asyncio
async def test_enqueue_dataset_ingest_routes_to_ingest_queue():
    """enqueue(task_type="dataset.ingest") must pass _queue_name="rag.ingest"."""
    from ragp_api.services.queue import enqueue

    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j2"))

    await enqueue(
        task_type="dataset.ingest",
        tenant_id="org-1",
        payload={"dataset_id": "ds-456"},
        arq_pool=pool,
    )

    pool.enqueue_job.assert_awaited_once()
    kwargs = pool.enqueue_job.call_args.kwargs
    assert pool.enqueue_job.call_args.args[0] == "run_dataset_ingest_task"
    assert kwargs["_queue_name"] == "rag.ingest"


@pytest.mark.asyncio
async def test_enqueue_unknown_task_type_raises():
    """enqueue() must raise ValueError for unregistered task types."""
    from ragp_api.services.queue import enqueue

    pool = MagicMock()
    pool.enqueue_job = AsyncMock()

    with pytest.raises(ValueError, match="Unknown task_type"):
        await enqueue(
            task_type="nonexistent.task",
            tenant_id="org-1",
            payload={},
            arq_pool=pool,
        )

    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_respects_explicit_queue_name_override():
    """Explicit queue_name= kwarg overrides the routing table."""
    from ragp_api.services.queue import enqueue

    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j3"))

    await enqueue(
        task_type="experiment.run",
        tenant_id="org-1",
        payload={"experiment_id": "exp-789"},
        queue_name="rag.custom",
        arq_pool=pool,
    )

    pool.enqueue_job.assert_awaited_once()
    assert pool.enqueue_job.call_args.kwargs["_queue_name"] == "rag.custom"
