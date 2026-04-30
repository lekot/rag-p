"""Unit tests for services/queue.py — envelope format and idempotency.

Uses fakeredis so no real Redis instance is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arq_pool_mock() -> MagicMock:
    """Return a mock that mimics an arq ArqRedis pool."""
    job = MagicMock()
    job.job_id = "arq-job-123"
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=job)
    pool.aclose = AsyncMock()
    return pool


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_without_idempotency_key_returns_new_task_id(fake_redis: FakeRedis):
    """enqueue() without idempotency_key generates a new task_id, deduplicated=False."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import enqueue

        result = await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-001"},
        )

    assert result["deduplicated"] is False
    assert result["task_id"]  # non-empty UUID string
    assert result["job_id"] == "arq-job-123"

    # enqueue_job was called once with the ARQ function name and envelope kwarg
    pool_mock.enqueue_job.assert_awaited_once()
    call_kwargs = pool_mock.enqueue_job.call_args.kwargs
    assert call_kwargs["envelope"]["task_type"] == "experiment.run"
    assert call_kwargs["envelope"]["tenant_id"] == "org-abc"
    assert call_kwargs["envelope"]["payload"] == {"experiment_id": "exp-001"}
    assert call_kwargs["envelope"]["task_id"] == result["task_id"]


@pytest.mark.asyncio
async def test_envelope_contains_required_keys(fake_redis: FakeRedis):
    """The envelope dict passed to ARQ must contain all required top-level keys."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import enqueue

        await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-002"},
        )

    envelope = pool_mock.enqueue_job.call_args.kwargs["envelope"]
    required_keys = {"task_id", "task_type", "tenant_id", "idempotency_key", "payload", "ts"}
    assert required_keys.issubset(
        envelope.keys()
    ), f"Missing keys: {required_keys - set(envelope.keys())}"


@pytest.mark.asyncio
async def test_idempotency_first_call_not_deduplicated(fake_redis: FakeRedis):
    """First call with an idempotency_key → deduplicated=False."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import enqueue

        result = await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-003"},
            idempotency_key="exp-003-run",
        )

    assert result["deduplicated"] is False
    assert result["task_id"]
    pool_mock.enqueue_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_second_call_is_deduplicated(fake_redis: FakeRedis):
    """Second call with the same idempotency_key → deduplicated=True, same task_id."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import enqueue

        first = await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-004"},
            idempotency_key="exp-004-run",
        )
        second = await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-004"},
            idempotency_key="exp-004-run",
        )

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["task_id"] == first["task_id"]
    # ARQ job was only submitted once
    assert pool_mock.enqueue_job.await_count == 1


@pytest.mark.asyncio
async def test_idempotency_key_ttl_is_24h(fake_redis: FakeRedis):
    """The Redis key for an idempotency lock must have TTL = 86400 (24 h)."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import _IDEM_PREFIX, enqueue

        idem_key = "exp-ttl-check"
        await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-005"},
            idempotency_key=idem_key,
        )

    redis_key = f"{_IDEM_PREFIX}{idem_key}"
    ttl = await fake_redis.ttl(redis_key)
    # TTL should be within 86400 (allow 1 second tolerance for test execution time)
    assert 86399 <= ttl <= 86400, f"Expected TTL ~86400 but got {ttl}"


@pytest.mark.asyncio
async def test_unknown_task_type_raises_value_error():
    """Passing an unregistered task_type must raise ValueError immediately."""
    from ragp_api.services.queue import enqueue

    with pytest.raises(ValueError, match="Unknown task_type"):
        await enqueue(
            task_type="nonexistent.task",
            tenant_id="org-abc",
            payload={},
        )


@pytest.mark.asyncio
async def test_second_dedup_returns_none_job_id(fake_redis: FakeRedis):
    """Deduplicated calls return job_id=None (no new ARQ job was submitted)."""
    pool_mock = _make_arq_pool_mock()

    with (
        patch("ragp_api.services.queue.create_pool", return_value=pool_mock),
        patch("ragp_api.services.queue.aioredis.Redis", return_value=fake_redis),
    ):
        from ragp_api.services.queue import enqueue

        await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-006"},
            idempotency_key="exp-006-run",
        )
        result = await enqueue(
            task_type="experiment.run",
            tenant_id="org-abc",
            payload={"experiment_id": "exp-006"},
            idempotency_key="exp-006-run",
        )

    assert result["job_id"] is None
