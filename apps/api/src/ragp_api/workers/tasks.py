"""ARQ task definitions for background experiment execution."""

from __future__ import annotations

import logging
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
