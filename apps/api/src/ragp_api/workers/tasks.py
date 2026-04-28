"""ARQ task definitions for background experiment execution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


async def run_experiment_task(ctx: dict[str, Any], experiment_id: str) -> None:
    """
    ARQ task: load Experiment from DB and run the evaluation grid.

    This task runs inside the ARQ worker process (not inside a FastAPI request).
    It creates its own DB session via the standalone async_session helper so it
    can operate outside of the request/dependency-injection lifecycle.
    """
    from sqlalchemy import select

    from ragp_api.db.models import Experiment
    from ragp_api.db.session import async_session
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
    from ragp_api.db.session import async_session

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
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
