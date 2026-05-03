"""ARQ task definitions for background experiment execution."""

from __future__ import annotations

import logging
import os
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
    experiment_watchdog_marked_failed_total = None


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


# ---------------------------------------------------------------------------
# Subscription lifecycle email notifications (cron)
# ---------------------------------------------------------------------------

# Notify users about plan expiry: a warning N days before the period ends and
# a notification once the period has elapsed.  Idempotent across cron runs via
# Redis SETNX keys with a TTL slightly longer than the notification window.

_EXPIRING_NOTICE_DAYS = 3
_EXPIRING_TTL_SECONDS = 4 * 24 * 3600  # 4 days
_EXPIRED_TTL_SECONDS = 7 * 24 * 3600  # 7 days


async def _redis_setnx_with_ttl(key: str, ttl_seconds: int) -> bool:
    """Try to claim *key* in Redis with TTL.  Returns True iff we won the race.

    Workers do not share the FastAPI app.state — open a short-lived connection
    per call.  Falls back to ``True`` (proceed) if Redis is unreachable so a
    worker outage does not silence emails forever; duplicates are far less bad
    than missed notifications and admins still see the cron error in logs.
    """
    import contextlib  # noqa: PLC0415

    import redis.asyncio as aioredis  # noqa: PLC0415

    from ragp_api.settings import settings  # noqa: PLC0415

    client: Any = None
    try:
        client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # SET key value NX EX ttl — atomic claim.
        result = await client.set(key, b"1", nx=True, ex=ttl_seconds)
        return bool(result)
    except Exception:
        logger.warning("redis SETNX failed for %s — proceeding without idempotency", key)
        return True
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()


async def notify_subscription_lifecycle_task(ctx: dict[str, Any]) -> dict[str, int]:
    """Cron task: send expiring/expired emails to org owners.

    Runs daily.  For each org subscription:
    - Active and ending within ``_EXPIRING_NOTICE_DAYS`` -> expiring email.
    - Just expired (status=expired and period_end is today) -> expired email.

    Idempotency: a Redis key per (org_id, period_end, kind) prevents the same
    notice firing twice across daily runs.

    Returns a dict ``{"expiring": N, "expired": M}`` for tests/metrics.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from ragp_api.db.models import OrgMember, OrgSubscription, Plan, User  # noqa: PLC0415
    from ragp_api.services.audit import log_audit_event  # noqa: PLC0415
    from ragp_api.services.email import (  # noqa: PLC0415
        send_subscription_expired_email,
        send_subscription_expiring_email,
    )

    now = datetime.now(UTC)
    expiring_cutoff = now + timedelta(days=_EXPIRING_NOTICE_DAYS)
    expired_cutoff = now - timedelta(days=1)

    sent_expiring = 0
    sent_expired = 0

    async with async_session() as db:
        # ---- Expiring soon (active subscriptions within window) ----
        active_result = await db.execute(
            select(OrgSubscription).where(
                OrgSubscription.status == "active",
                OrgSubscription.current_period_end >= now,
                OrgSubscription.current_period_end <= expiring_cutoff,
            )
        )
        for sub in active_result.scalars().all():
            period_end = sub.current_period_end
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=UTC)
            key = f"email:expiring:{sub.org_id}:{period_end.date().isoformat()}"
            if not await _redis_setnx_with_ttl(key, _EXPIRING_TTL_SECONDS):
                continue

            owner_email = await db.scalar(
                select(User.email)
                .join(OrgMember, OrgMember.user_id == User.id)
                .where(OrgMember.org_id == sub.org_id, OrgMember.role == "owner")
                .order_by(OrgMember.created_at)
                .limit(1)
            )
            if not owner_email:
                continue

            plan = await db.scalar(select(Plan).where(Plan.id == sub.plan_id))
            plan_label = plan.name if plan is not None else sub.plan_id
            days_left = max(0, (period_end - now).days)
            try:
                await send_subscription_expiring_email(
                    owner_email,
                    plan_label,
                    period_end.isoformat(),
                    days_left,
                )
                await log_audit_event(
                    db,
                    org_id=sub.org_id,
                    user_id=None,
                    event_type="email.sent",
                    resource_type="email",
                    resource_id=None,
                    metadata={
                        "kind": "subscription_expiring",
                        "plan_id": sub.plan_id,
                        "expires_at": period_end.isoformat(),
                        "days_left": days_left,
                    },
                )
                sent_expiring += 1
            except Exception:
                logger.exception("expiring email failed for org %s", sub.org_id)

        # ---- Just-expired (status=expired and ended in the last 24h) ----
        expired_result = await db.execute(
            select(OrgSubscription).where(
                OrgSubscription.status == "expired",
                OrgSubscription.current_period_end >= expired_cutoff,
                OrgSubscription.current_period_end <= now,
            )
        )
        for sub in expired_result.scalars().all():
            period_end = sub.current_period_end
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=UTC)
            key = f"email:expired:{sub.org_id}:{period_end.date().isoformat()}"
            if not await _redis_setnx_with_ttl(key, _EXPIRED_TTL_SECONDS):
                continue

            owner_email = await db.scalar(
                select(User.email)
                .join(OrgMember, OrgMember.user_id == User.id)
                .where(OrgMember.org_id == sub.org_id, OrgMember.role == "owner")
                .order_by(OrgMember.created_at)
                .limit(1)
            )
            if not owner_email:
                continue

            plan = await db.scalar(select(Plan).where(Plan.id == sub.plan_id))
            plan_label = plan.name if plan is not None else sub.plan_id
            try:
                await send_subscription_expired_email(owner_email, plan_label)
                await log_audit_event(
                    db,
                    org_id=sub.org_id,
                    user_id=None,
                    event_type="email.sent",
                    resource_type="email",
                    resource_id=None,
                    metadata={"kind": "subscription_expired", "plan_id": sub.plan_id},
                )
                sent_expired += 1
            except Exception:
                logger.exception("expired email failed for org %s", sub.org_id)

        await db.commit()

    logger.info(
        "notify_subscription_lifecycle_task: expiring=%d expired=%d",
        sent_expiring,
        sent_expired,
    )
    return {"expiring": sent_expiring, "expired": sent_expired}


async def run_experiment_task(
    ctx: dict[str, Any],
    envelope: dict[str, Any] | None = None,
    # Legacy positional arg kept for backward-compat with any jobs enqueued
    # before the envelope migration.  New callers always pass `envelope`.
    experiment_id: str | None = None,
) -> None:
    """
    ARQ task: load Experiment from DB and run the evaluation grid.

    This task runs inside the ARQ worker process (not inside a FastAPI request).
    It creates its own DB session via the standalone async_session helper so it
    can operate outside of the request/dependency-injection lifecycle.

    Accepts tasks enqueued via the new ``services.queue.enqueue()`` helper
    (which passes ``envelope=<dict>``) as well as legacy direct
    ``pool.enqueue_job("run_experiment_task", <experiment_id>)`` calls.
    """
    # Resolve experiment_id from envelope (new path) or legacy positional arg.
    if envelope is not None:
        experiment_id = envelope.get("payload", {}).get("experiment_id") or envelope.get("task_id")

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


async def chunk_document(ctx: dict[str, Any], document_id: str, text: str) -> None:
    """ARQ task: chunk and embed a document in the background.

    Uses the default recursive-character chunker, then embeds via the
    first available embedder (Ollama → Cohere → OpenAI).
    Updates document status to "indexed" on success or "failed" on error.
    """
    from typing import cast

    from sqlalchemy import select

    from ragp_api.db.models import Chunk, Document
    from ragp_api.plugins.base import Chunker, Embedder
    from ragp_api.plugins.registry import get_plugin

    logger.info("chunk_document: start doc=%s len=%d", document_id, len(text))

    async with async_session() as db:
        try:
            # Resolve document
            doc_result = await db.execute(select(Document).where(Document.id == document_id))
            doc = doc_result.scalar_one_or_none()
            if doc is None:
                logger.error("chunk_document: document %s not found", document_id)
                return

            # Chunk
            chunker_cls = get_plugin("chunker", "recursive-character")
            if chunker_cls is None:
                raise RuntimeError("Default chunker recursive-character not registered")
            chunker = cast(Chunker, chunker_cls({}))
            raw_chunks = await chunker.chunk(text)

            # Build Chunk objects
            chunk_objs = []
            for i, rc in enumerate(raw_chunks):
                meta: dict[str, Any] = {"chunk_index": i}
                if isinstance(rc.get("metadata"), dict):
                    meta.update(rc["metadata"])
                chunk_objs.append(
                    Chunk(
                        id=str(uuid.uuid4()),
                        document_id=doc.id,
                        organization_id=doc.organization_id,
                        text=rc["text"],
                        embedding=None,
                        metadata_json=meta,
                    )
                )
            db.add_all(chunk_objs)
            await db.flush()

            # Embed
            ollama_host = os.environ.get("OLLAMA_HOST", "")
            cohere_key = os.environ.get("COHERE_API_KEY", "")
            openai_key = os.environ.get("OPENAI_API_KEY", "")
            embedder: Embedder | None = None
            if ollama_host:
                cls = get_plugin("embedder", "ollama-embedder")
                if cls is not None:
                    embedder = cast(Embedder, cls({"model": "bge-m3"}))
            elif cohere_key:
                cls = get_plugin("embedder", "cohere-embedder")
                if cls is not None:
                    embedder = cast(
                        Embedder, cls({"model": "embed-multilingual-v3.0", "input_type": "search_document"})
                    )
            elif openai_key:
                cls = get_plugin("embedder", "litellm-embedder")
                if cls is not None:
                    embedder = cast(Embedder, cls({"model": "openai/text-embedding-3-small"}))

            if embedder is not None:
                texts = [c.text for c in chunk_objs]
                vectors = await embedder.embed(texts)
                for chunk_obj, vec in zip(chunk_objs, vectors, strict=False):
                    chunk_obj.embedding = vec

            doc.status = "indexed"
            await db.commit()
            logger.info("chunk_document: done doc=%s chunks=%d", document_id, len(chunk_objs))

        except Exception:
            logger.exception("chunk_document: failed doc=%s", document_id)
            try:
                doc.status = "failed"
                await db.commit()
            except Exception:
                pass


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
