"""Tests for the experiment watchdog (stale-cron + on_job_failure).

The watchdog rescues experiments stuck in queued/running when the ARQ
worker dies or hits ``job_timeout``.  These tests exercise both code
paths against the in-memory SQLite engine the rest of the suite uses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragp_api.db.models import Dataset, Experiment


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_experiment(
    *,
    organization_id: str,
    dataset_id: str,
    status: str,
    updated_at: datetime,
    leaderboard_json: list | None = None,
) -> Experiment:
    return Experiment(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        name="watchdog test exp",
        dataset_id=dataset_id,
        plugin_grid_json={"retrievers": []},
        status=status,
        leaderboard_json=leaderboard_json,
        updated_at=updated_at,
    )


@pytest_asyncio.fixture
async def patched_async_session(db_engine):
    """Patch ragp_api.db.session.async_session to use the test engine.

    The watchdog code opens its own session via ``async_session()`` which
    normally points at the production engine.  Redirect it at the test
    engine so the cron sees the rows we just inserted.
    """
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("ragp_api.workers.tasks.async_session", factory),
        patch("ragp_api.db.session.async_session", factory),
    ):
        yield factory


@pytest_asyncio.fixture
async def dataset(db_session: AsyncSession, organization_id: str) -> str:
    ds = Dataset(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        name="watchdog ds",
    )
    db_session.add(ds)
    await db_session.commit()
    return ds.id


@pytest.mark.asyncio
async def test_watchdog_marks_running_experiment_failed_after_timeout(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.tasks import mark_stale_experiments_failed

    stale_at = _utcnow() - timedelta(minutes=30)
    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="running",
        updated_at=stale_at,
    )
    db_session.add(exp)
    await db_session.commit()

    marked = await mark_stale_experiments_failed({})
    assert marked == 1

    # Re-fetch in a fresh session to bypass identity-map caching.
    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == exp.id))
        ).scalar_one()
        assert refreshed.status == "failed"
        payload = refreshed.leaderboard_json
        assert isinstance(payload, list) and payload
        assert payload[0]["error_code"] == "worker_timeout"
        assert payload[0]["stale_for_seconds"] >= 60 * 25
        # updated_at bumped to "now" once we marked it failed.  SQLite drops
        # tzinfo on round-trip so we normalise both sides to naive UTC.
        bumped = refreshed.updated_at
        if bumped.tzinfo is not None:
            bumped = bumped.astimezone(UTC).replace(tzinfo=None)
        baseline = (stale_at + timedelta(minutes=20)).replace(tzinfo=None)
        assert bumped >= baseline


@pytest.mark.asyncio
async def test_watchdog_does_not_touch_recent_experiment(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.tasks import mark_stale_experiments_failed

    fresh_at = _utcnow() - timedelta(seconds=30)
    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="running",
        updated_at=fresh_at,
    )
    db_session.add(exp)
    await db_session.commit()

    marked = await mark_stale_experiments_failed({})
    assert marked == 0

    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == exp.id))
        ).scalar_one()
        assert refreshed.status == "running"


@pytest.mark.asyncio
async def test_watchdog_idempotent_on_already_completed(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.tasks import mark_stale_experiments_failed

    completed = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="completed",
        updated_at=_utcnow() - timedelta(hours=2),
        leaderboard_json=[{"composite_score": 0.9}],
    )
    db_session.add(completed)
    await db_session.commit()

    marked = await mark_stale_experiments_failed({})
    assert marked == 0

    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == completed.id))
        ).scalar_one()
        assert refreshed.status == "completed"
        assert refreshed.leaderboard_json == [{"composite_score": 0.9}]


@pytest.mark.asyncio
async def test_watchdog_handles_queued_status(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.tasks import mark_stale_experiments_failed

    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="queued",
        updated_at=_utcnow() - timedelta(hours=1),
    )
    db_session.add(exp)
    await db_session.commit()

    marked = await mark_stale_experiments_failed({})
    assert marked == 1

    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == exp.id))
        ).scalar_one()
        assert refreshed.status == "failed"
        assert refreshed.leaderboard_json[0]["error_code"] == "worker_timeout"


@pytest.mark.asyncio
async def test_on_job_failure_marks_experiment_failed(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.main import on_job_failure

    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="running",
        updated_at=_utcnow(),
    )
    db_session.add(exp)
    await db_session.commit()

    ctx = {
        "function": "run_experiment_task",
        "args": (exp.id,),
        "exception": RuntimeError("boom: worker SIGKILL"),
        "job_id": "job-abc",
    }
    await on_job_failure(ctx)

    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == exp.id))
        ).scalar_one()
        assert refreshed.status == "failed"
        assert refreshed.leaderboard_json[0]["error_code"] == "worker_crash"
        assert "boom" in refreshed.leaderboard_json[0]["error"]


@pytest.mark.asyncio
async def test_on_job_failure_ignores_other_functions(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
    patched_async_session,
):
    from ragp_api.workers.main import on_job_failure

    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="running",
        updated_at=_utcnow(),
    )
    db_session.add(exp)
    await db_session.commit()

    ctx = {
        "function": "aggregate_usage_daily",
        "args": (),
        "exception": RuntimeError("nope"),
    }
    await on_job_failure(ctx)

    async with patched_async_session() as session:
        refreshed = (
            await session.execute(select(Experiment).where(Experiment.id == exp.id))
        ).scalar_one()
        assert refreshed.status == "running"


@pytest.mark.asyncio
async def test_on_job_failure_swallows_exceptions(monkeypatch):
    """The hook must never raise — a broken DB call should be logged, not crash the worker."""
    from ragp_api.workers import main as workers_main

    async def boom(*_a, **_kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(workers_main, "mark_experiment_failed_on_crash", boom)

    # Should NOT raise.
    await workers_main.on_job_failure(
        {
            "function": "run_experiment_task",
            "args": ("nonexistent-id",),
            "exception": RuntimeError("worker died"),
        }
    )


@pytest.mark.asyncio
async def test_experiment_runner_updates_updated_at_on_each_commit(
    db_session: AsyncSession,
    organization_id: str,
    dataset: str,
):
    """Heartbeat sanity: the runner bumps updated_at as it progresses."""
    from ragp_api.services.experiment_runner import run_experiment_inline

    exp = _make_experiment(
        organization_id=organization_id,
        dataset_id=dataset,
        status="queued",
        updated_at=_utcnow() - timedelta(hours=1),
    )
    db_session.add(exp)
    await db_session.commit()
    # Normalise tzinfo: SQLite drops it on round-trip, so capture both via a
    # refresh so we compare like-with-like below.
    await db_session.refresh(exp)
    initial_updated_at = exp.updated_at

    # Empty plugin grid → build_combinations returns [] → no per-combo commit
    # path runs, but status='running' and the final commit will still bump
    # updated_at, which is what the watchdog cares about.
    exp.plugin_grid_json = {}
    await db_session.commit()

    await run_experiment_inline(exp, db_session)

    await db_session.refresh(exp)
    assert exp.status in {"completed", "failed"}
    assert exp.updated_at > initial_updated_at
