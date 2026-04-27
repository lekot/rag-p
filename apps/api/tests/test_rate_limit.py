"""Tests for rate limiting on POST /api/v1/rag/query."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import ApiKey, Dataset, Membership, Organization, User
from ragp_api.db.redis import get_redis
from ragp_api.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_org_with_key(
    db: AsyncSession,
    raw_key: str = "rgp_ratelimitkey000000000000000001",
) -> tuple[str, str, str, str]:
    """Create org + user + api_key + dataset.

    Returns (org_id, raw_key, api_key_id, dataset_id).
    """
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    org = Organization(id=org_id, name="ratelimitorg", slug=f"rl-{org_id[:8]}")
    user = User(id=user_id, email=f"rl-{org_id[:8]}@example.com", password_hash="x")
    membership = Membership(organization_id=org_id, user_id=user_id, role="admin")

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key_id = str(uuid.uuid4())
    api_key = ApiKey(
        id=api_key_id,
        organization_id=org_id,
        user_id=user_id,
        name="rl-test-key",
        key_prefix=raw_key[:8],
        key_hash=key_hash,
    )

    dataset = Dataset(
        id=str(uuid.uuid4()), organization_id=org_id, name="RL DS", source="uploaded"
    )

    db.add_all([org, user, membership, api_key, dataset])
    await db.commit()

    return org_id, raw_key, api_key_id, dataset.id


def _fake_get_plugin(
    mock_retriever: Any,
    mock_generator: Any,
) -> Any:
    """Return a get_plugin side-effect that routes by kind."""

    def _side_effect(kind: str, name: str) -> Any:
        if kind == "retriever":
            return lambda _p: mock_retriever
        return lambda _p: mock_generator

    return _side_effect


# ---------------------------------------------------------------------------
# test_rate_limit_per_key_blocks_after_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_per_key_blocks_after_limit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """N+1 requests with same key must receive 429 on the (N+1)-th request."""
    _org_id, raw_key, _key_id, dataset_id = await _create_org_with_key(db_session)

    fake_redis = FakeRedis()
    limit = 3

    async def override_get_redis() -> AsyncIterator[FakeRedis]:
        yield fake_redis

    from ragp_api.settings import settings as _settings

    original_key_limit = _settings.rate_limit_per_key_rpm
    _settings.rate_limit_per_key_rpm = limit
    app.dependency_overrides[get_redis] = override_get_redis

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(
        return_value=[
            {
                "id": "c1",
                "text": "hello",
                "score": 0.9,
                "document_id": "d1",
                "document_name": "f.txt",
            }
        ]
    )
    mock_generator = AsyncMock()
    mock_generator.generate = AsyncMock(
        return_value={
            "answer": "ok",
            "trace": {"usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        }
    )

    try:
        with (
            patch(
                "ragp_api.api.v1.routes_rag.get_plugin",
                side_effect=_fake_get_plugin(mock_retriever, mock_generator),
            ),
            patch(
                "ragp_api.api.v1.routes_rag._resolve_embedder",
                new=AsyncMock(return_value=(None, "none")),
            ),
        ):
            # First N requests must succeed
            for i in range(limit):
                resp = await client.post(
                    "/api/v1/rag/query",
                    headers={"Authorization": f"Bearer {raw_key}"},
                    json={"dataset_id": dataset_id, "query": f"q{i}"},
                )
                assert resp.status_code == 200, (
                    f"Request {i + 1} unexpectedly blocked: {resp.text}"
                )

            # (N+1)-th must be blocked
            resp = await client.post(
                "/api/v1/rag/query",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"dataset_id": dataset_id, "query": "over-limit"},
            )
            assert resp.status_code == 429, (
                f"Expected 429, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body["detail"]["detail"] == "rate_limit_exceeded"
            assert body["detail"]["scope"] == "key"
            assert body["detail"]["limit"] == limit
            assert "Retry-After" in resp.headers
    finally:
        _settings.rate_limit_per_key_rpm = original_key_limit
        app.dependency_overrides.pop(get_redis, None)
        await fake_redis.aclose()


# ---------------------------------------------------------------------------
# test_rate_limit_per_org_blocks_when_multiple_keys_exhaust
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_per_org_blocks_when_multiple_keys_exhaust(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Two keys in one org together exhausting org limit → 429 with scope=org."""
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    org = Organization(id=org_id, name="rl-org2", slug=f"rl2-{org_id[:8]}")
    user = User(id=user_id, email=f"rl2-{org_id[:8]}@example.com", password_hash="x")
    membership = Membership(organization_id=org_id, user_id=user_id, role="admin")

    raw_key_a = "rgp_orgkeyAAAAAAAAAAAAAAAAAAAAAAAA"
    raw_key_b = "rgp_orgkeyBBBBBBBBBBBBBBBBBBBBBBBB"

    def _make_api_key(raw: str) -> ApiKey:
        return ApiKey(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            user_id=user_id,
            name=f"key-{raw[4:8]}",
            key_prefix=raw[:8],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        )

    api_key_a = _make_api_key(raw_key_a)
    api_key_b = _make_api_key(raw_key_b)
    dataset = Dataset(
        id=str(uuid.uuid4()), organization_id=org_id, name="RL DS2", source="uploaded"
    )

    db_session.add_all([org, user, membership, api_key_a, api_key_b, dataset])
    await db_session.commit()

    fake_redis = FakeRedis()
    org_limit = 3
    key_limit = 100  # high enough to not block per-key

    from ragp_api.settings import settings as _settings

    original_key_limit = _settings.rate_limit_per_key_rpm
    original_org_limit = _settings.rate_limit_per_org_rpm
    _settings.rate_limit_per_key_rpm = key_limit
    _settings.rate_limit_per_org_rpm = org_limit

    async def override_get_redis() -> AsyncIterator[FakeRedis]:
        yield fake_redis

    app.dependency_overrides[get_redis] = override_get_redis

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    try:
        with (
            patch(
                "ragp_api.api.v1.routes_rag.get_plugin",
                side_effect=_fake_get_plugin(mock_retriever, AsyncMock()),
            ),
            patch(
                "ragp_api.api.v1.routes_rag._resolve_embedder",
                new=AsyncMock(return_value=(None, "none")),
            ),
        ):
            # Send requests alternating between two keys until org limit is hit
            keys = [raw_key_a, raw_key_b, raw_key_a]
            for i, key in enumerate(keys):
                resp = await client.post(
                    "/api/v1/rag/query",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"dataset_id": dataset.id, "query": f"q{i}"},
                )
                # retriever returns empty → 200 with no-chunks answer
                assert resp.status_code == 200, (
                    f"Request {i + 1} unexpectedly blocked: {resp.text}"
                )

            # The 4th request (over org_limit=3) should be blocked
            resp = await client.post(
                "/api/v1/rag/query",
                headers={"Authorization": f"Bearer {raw_key_b}"},
                json={"dataset_id": dataset.id, "query": "over-org-limit"},
            )
            assert resp.status_code == 429, (
                f"Expected 429, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body["detail"]["detail"] == "rate_limit_exceeded"
            assert body["detail"]["scope"] == "org"
            assert body["detail"]["limit"] == org_limit
    finally:
        _settings.rate_limit_per_key_rpm = original_key_limit
        _settings.rate_limit_per_org_rpm = original_org_limit
        app.dependency_overrides.pop(get_redis, None)
        await fake_redis.aclose()


# ---------------------------------------------------------------------------
# test_rate_limit_redis_down_fail_open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_redis_down_fail_open(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When Redis raises ConnectionError, the request must still succeed (fail-open)."""
    _org_id, raw_key, _key_id, dataset_id = await _create_org_with_key(
        db_session,
        raw_key="rgp_redisdownkey0000000000000000001",
    )

    class _BrokenRedis:
        def pipeline(self) -> Any:
            raise ConnectionError("Redis is down")

    async def override_get_redis() -> AsyncIterator[_BrokenRedis]:
        yield _BrokenRedis()

    app.dependency_overrides[get_redis] = override_get_redis

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(
        return_value=[
            {
                "id": "c1",
                "text": "hello",
                "score": 0.9,
                "document_id": "d1",
                "document_name": "f.txt",
            }
        ]
    )
    mock_generator = AsyncMock()
    mock_generator.generate = AsyncMock(
        return_value={
            "answer": "ok",
            "trace": {"usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        }
    )

    try:
        with (
            patch(
                "ragp_api.api.v1.routes_rag.get_plugin",
                side_effect=_fake_get_plugin(mock_retriever, mock_generator),
            ),
            patch(
                "ragp_api.api.v1.routes_rag._resolve_embedder",
                new=AsyncMock(return_value=(None, "none")),
            ),
        ):
            resp = await client.post(
                "/api/v1/rag/query",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"dataset_id": dataset_id, "query": "redis is down"},
            )
            # Must pass through despite Redis being down
            assert resp.status_code == 200, (
                f"Expected 200 (fail-open), got {resp.status_code}: {resp.text}"
            )
    finally:
        app.dependency_overrides.pop(get_redis, None)
