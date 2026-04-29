"""ARQ task definitions for background experiment execution."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from ragp_api.db.session import async_session

logger = logging.getLogger(__name__)

# Optional Prometheus counter — guarded so a duplicate registration (e.g. when
# tests reload the module under pytest) does not blow up at import time.  We
# look the metric up in the default registry first and only create it once.
try:  # pragma: no cover — import guard
    from prometheus_client import REGISTRY, Counter

    _METRIC_NAME = "ragp_experiment_watchdog_marked_failed_total"
    _existing = getattr(REGISTRY, "_names_to_collectors", {}).get(_METRIC_NAME)
    if _existing is not None:
        experiment_watchdog_marked_failed_total = _existing
    else:
        experiment_watchdog_marked_failed_total = Counter(
            _METRIC_NAME,
            "Experiments force-failed by the stale-experiment watchdog",
        )
except Exception:  # pragma: no cover
    experiment_watchdog_marked_failed_total = None  # type: ignore[assignment]


async def mark_stale_experiments_failed(ctx: dict[str, Any] | None = None) -> int:
    """Watchdog: force-fail experiments stuck in queued/running.

    A row is considered stale when ``updated_at`` is older than
    ``settings.experiment_stale_timeout_seconds``.  We use
    ``FOR UPDATE SKIP LOCKED`` on Postgres so multiple worker processes can
    run the cron concurrently without stepping on each other; on SQLite (used
    in tests) we silently fall back to a plain SELECT — there are no concurrent
    workers in unit tests.

    Returns the number of experiments marked failed (useful for tests/metrics).
    """
    from sqlalchemy import select

    from ragp_api.db.models import Experiment
    from ragp_api.settings import settings

    cutoff = datetime.now(UTC) - timedelta(seconds=settings.experiment_stale_timeout_seconds)
    marked = 0

    async with async_session() as db:
        # On SQLite (test backend) timestamps come back tz-naive, so the
        # comparison must use the same flavour.  On Postgres TIMESTAMPTZ this
        # is automatically aware, but a cutoff in either form serialises to
        # the same SQL literal so it's fine to feed in tz-aware unconditionally
        # — the only place we need to be careful is in Python-side arithmetic
        # below (see _normalise call).
        stmt = (
            select(Experiment)
            .where(
                Experiment.status.in_(("queued", "running")),
                Experiment.updated_at < cutoff,
            )
            .limit(100)
        )
        # Postgres supports row-level locking with skip-locked semantics.  On
        # other dialects (SQLite for tests) we just run the plain query.
        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        result = await db.execute(stmt)
        stale = list(result.scalars().all())

        now = datetime.now(UTC)
        for experiment in stale:
            # SQLite (used in tests) strips tzinfo on round-trip; normalise so
            # the subtraction below is always tz-aware.
            updated = experiment.updated_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            stale_for = int((now - updated).total_seconds()) if updated else 0
            experiment.status = "failed"
            experiment.leaderboard_json = [
                {
                    "error_code": "worker_timeout",
                    "error": (
                        "Experiment exceeded watchdog timeout — worker likely crashed "
                        "or hit job_timeout."
                    ),
                    "stale_for_seconds": stale_for,
                }
            ]
            experiment.updated_at = now
            marked += 1

        if marked:
            await db.commit()
            logger.warning(
                "mark_stale_experiments_failed: force-failed %d stale experiment(s)",
                marked,
            )
            if experiment_watchdog_marked_failed_total is not None:
                experiment_watchdog_marked_failed_total.inc(marked)

    return marked


async def mark_experiment_failed_on_crash(experiment_id: str, error: str) -> bool:
    """Mark a single experiment as crashed (used by on_job_failure callback).

    Returns True iff a row transitioned to ``failed``.  Idempotent: rows
    already in a terminal state are left untouched.
    """
    from sqlalchemy import select

    from ragp_api.db.models import Experiment

    async with async_session() as db:
        result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
        experiment = result.scalar_one_or_none()
        if experiment is None:
            logger.warning(
                "mark_experiment_failed_on_crash: experiment %s not found", experiment_id
            )
            return False
        if experiment.status not in ("queued", "running"):
            return False

        experiment.status = "failed"
        experiment.leaderboard_json = [
            {
                "error_code": "worker_crash",
                "error": error or "Worker crashed before completing the experiment",
            }
        ]
        experiment.updated_at = datetime.now(UTC)
        await db.commit()

    logger.warning("mark_experiment_failed_on_crash: experiment %s marked failed", experiment_id)
    return True


async def expire_subscriptions_task(ctx: dict[str, Any]) -> None:
    """Cron task: mark expired all subscriptions whose period has ended.

    Runs daily at 00:10 UTC via WorkerSettings.cron_jobs.
    """
    from ragp_api.services.subscription import expire_old_subscriptions

    logger.info("expire_subscriptions_task: starting")
    async with async_session() as db:
        count = await expire_old_subscriptions(db)
        await db.commit()
    logger.info("expire_subscriptions_task: expired %d subscriptions", count)


async def run_experiment_task(ctx: dict[str, Any], experiment_id: str) -> None:
    """
    ARQ task: load Experiment from DB and run the evaluation grid.

    This task runs inside the ARQ worker process (not inside a FastAPI request).
    It creates its own DB session via the standalone async_session helper so it
    can operate outside of the request/dependency-injection lifecycle.
    """
    from sqlalchemy import select

    from ragp_api.db.models import Experiment
    from ragp_api.services.experiment_runner import run_experiment_inline

    logger.info("Starting experiment task for experiment_id=%s", experiment_id)

    async with async_session() as db:
        result = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
        experiment = result.scalar_one_or_none()
        if experiment is None:
            logger.error("Experiment %s not found — task aborted", experiment_id)
            return

        await run_experiment_inline(experiment, db)

    logger.info("Experiment task completed for experiment_id=%s", experiment_id)


async def aggregate_usage_daily(ctx: dict[str, Any]) -> None:
    """Aggregate usage_events for yesterday into usage_daily.

    Idempotent — uses SELECT + UPDATE OR INSERT on (org_id, day, model).
    Runs daily at 01:00 UTC via WorkerSettings.cron_jobs.
    """
    from sqlalchemy import func, select

    from ragp_api.db.models import UsageDaily, UsageEvent

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    logger.info("aggregate_usage_daily: aggregating for %s", yesterday)

    async with async_session() as db:
        result = await db.execute(
            select(
                UsageEvent.org_id,
                UsageEvent.model,
                func.sum(UsageEvent.prompt_tokens).label("total_prompt"),
                func.sum(UsageEvent.completion_tokens).label("total_completion"),
                func.sum(UsageEvent.cost_usd).label("total_cost"),
                func.count(UsageEvent.id).label("req_count"),
            )
            .where(func.date(UsageEvent.ts) == yesterday)
            .group_by(UsageEvent.org_id, UsageEvent.model)
        )
        rows = result.all()

        for row in rows:
            org_id, model, total_prompt, total_completion, total_cost, req_count = row

            existing_result = await db.execute(
                select(UsageDaily).where(
                    UsageDaily.org_id == org_id,
                    UsageDaily.day == yesterday,
                    UsageDaily.model == model,
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing is not None:
                existing.total_prompt_tokens = int(total_prompt or 0)
                existing.total_completion_tokens = int(total_completion or 0)
                existing.total_cost_usd = Decimal(str(total_cost or 0))
                existing.request_count = int(req_count or 0)
            else:
                daily = UsageDaily(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    day=yesterday,
                    model=model,
                    total_prompt_tokens=int(total_prompt or 0),
                    total_completion_tokens=int(total_completion or 0),
                    total_cost_usd=Decimal(str(total_cost or 0)),
                    request_count=int(req_count or 0),
                )
                db.add(daily)

        await db.commit()

    logger.info(
        "aggregate_usage_daily: done for %s — %d model-org combos processed",
        yesterday,
        len(rows),
    )
