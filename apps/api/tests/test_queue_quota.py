"""Unit tests for per-tenant queue quota enforcement (Phase 3).

Uses fakeredis so no real Redis instance is needed.

Scenarios covered:
- 5 enqueues on rag.experiment for one tenant — all succeed.
- 6th enqueue — QuotaExceededError raised, retry_after_seconds in (0, window].
- 5 enqueues by 5 different tenants — all succeed (per-tenant, not global).
- After window passes (window_seconds=1 fixture) — quota resets.
- rag.maintenance — no cap, 100 enqueues pass without error.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from ragp_api.services.queue import QuotaExceededError, _check_tenant_quota

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _make_arq_pool_mock() -> MagicMock:
    """Return a mock that mimics an arq ArqRedis pool."""
    job = MagicMock()
    job.job_id = "arq-job-999"
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=job)
    pool.aclose = AsyncMock()
    return pool


# ---------------------------------------------------------------------------
# _check_tenant_quota unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experiment_quota_5_ok(fake_redis: FakeRedis) -> None:
    """5 enqueues within the window for one tenant on rag.experiment — all succeed."""
    for _ in range(5):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-alpha",
            queue_name="rag.experiment",
            window_seconds=60,
            cap=5,
        )
    # No exception raised — test passes.


@pytest.mark.asyncio
async def test_experiment_quota_6th_raises(fake_redis: FakeRedis) -> None:
    """6th enqueue exceeds cap=5 — QuotaExceededError raised."""
    for _ in range(5):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-alpha",
            queue_name="rag.experiment",
            window_seconds=60,
            cap=5,
        )

    with pytest.raises(QuotaExceededError) as exc_info:
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-alpha",
            queue_name="rag.experiment",
            window_seconds=60,
            cap=5,
        )

    err = exc_info.value
    assert err.queue == "rag.experiment"
    assert err.tenant_id == "tenant-alpha"
    assert 0 < err.retry_after_seconds <= 60


@pytest.mark.asyncio
async def test_per_tenant_isolation(fake_redis: FakeRedis) -> None:
    """5 different tenants each making 1 enqueue — all succeed (not global quota)."""
    for i in range(5):
        await _check_tenant_quota(
            fake_redis,
            tenant_id=f"tenant-{i}",
            queue_name="rag.experiment",
            window_seconds=60,
            cap=5,
        )
    # No exception raised — quotas are per-tenant.


@pytest.mark.asyncio
async def test_quota_resets_after_window(fake_redis: FakeRedis) -> None:
    """After the window expires, the tenant can enqueue again."""
    # Use a tiny 1-second window so we can wait it out in the test.
    window = 1

    for _ in range(5):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-beta",
            queue_name="rag.experiment",
            window_seconds=window,
            cap=5,
        )

    # Verify we're at the cap.
    with pytest.raises(QuotaExceededError):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-beta",
            queue_name="rag.experiment",
            window_seconds=window,
            cap=5,
        )

    # Wait for the window to pass.
    await asyncio.sleep(window + 0.1)

    # Now the same tenant can enqueue 5 more times.
    for _ in range(5):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-beta",
            queue_name="rag.experiment",
            window_seconds=window,
            cap=5,
        )


@pytest.mark.asyncio
async def test_maintenance_no_cap(fake_redis: FakeRedis) -> None:
    """rag.maintenance has no cap — 100 enqueues pass without error."""
    for _ in range(100):
        await _check_tenant_quota(
            fake_redis,
            tenant_id="tenant-gamma",
            queue_name="rag.maintenance",
            window_seconds=60,
            cap=None,  # explicitly pass None; mirrors _queue_caps()["rag.maintenance"]
        )
    # No exception raised — maintenance is uncapped.


# ---------------------------------------------------------------------------
# Integration test: enqueue() raises QuotaExceededError via fake redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_raises_quota_exceeded(fake_redis: FakeRedis) -> None:
    """enqueue() with queue_name='rag.experiment' raises QuotaExceededError at cap+1."""
    pool_mock = _make_arq_pool_mock()

    # We need to intercept both the aioredis.Redis constructor (used by enqueue)
    # and the create_pool (used for ARQ).
    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
        patch("ragp_api.services.queue.settings.queue_quota_experiment_per_tenant", 5),
        patch("ragp_api.services.queue.settings.queue_quota_window_seconds", 60),
    ):
        from ragp_api.services.queue import enqueue

        # 5 should succeed.
        for i in range(5):
            result = await enqueue(
                task_type="experiment.run",
                tenant_id="tenant-delta",
                payload={"experiment_id": f"exp-{i}"},
                queue_name="rag.experiment",
            )
            assert result["deduplicated"] is False

        # 6th should raise.
        with pytest.raises(QuotaExceededError) as exc_info:
            await enqueue(
                task_type="experiment.run",
                tenant_id="tenant-delta",
                payload={"experiment_id": "exp-6"},
                queue_name="rag.experiment",
            )

    err = exc_info.value
    assert err.queue == "rag.experiment"
    assert err.tenant_id == "tenant-delta"
    assert 0 < err.retry_after_seconds <= 60
