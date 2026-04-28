"""Tests for usage tracking — service, aggregator, and API endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    ApiKey,
    Dataset,
    Membership,
    OrgMember,
    Organization,
    User,
    UsageDaily,
    UsageEvent,
)
from ragp_api.services.usage import calculate_cost, record_usage_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str,
    password: str = "s3cr3t!",
    org_name: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"email": email, "password": password}
    if org_name:
        body["organization_name"] = org_name
    resp = await client.post("/api/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str = "s3cr3t!") -> dict[str, Any]:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_org_with_api_key(
    db: AsyncSession,
) -> tuple[str, str, str]:
    """Create org + user (owner in org_members) + api_key. Returns (org_id, raw_key, user_id)."""
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    org = Organization(id=org_id, name="usage-org", slug=f"usage-{org_id[:8]}")
    user = User(id=user_id, email=f"usage-{org_id[:8]}@example.com", password_hash="x")
    membership = Membership(organization_id=org_id, user_id=user_id, role="admin")
    org_member = OrgMember(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        role="owner",
    )

    raw_key = "rgp_usage_" + "a1b2c3d4e5f6a7b8c9"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=user_id,
        name="usage-test-key",
        key_prefix=raw_key[:8],
        key_hash=key_hash,
    )

    db.add_all([org, user, membership, org_member, api_key])
    await db.commit()
    return org_id, raw_key, user_id


# ---------------------------------------------------------------------------
# Unit tests — calculate_cost
# ---------------------------------------------------------------------------


def test_calculate_cost_deepseek_correct() -> None:
    """Known values for deepseek/deepseek-v4-flash pricing."""
    # 1000 prompt tokens * 0.00027 / 1000 + 1000 completion * 0.0011 / 1000
    # = 0.00027 + 0.0011 = 0.00137
    cost = calculate_cost("deepseek/deepseek-v4-flash", 1000, 1000)
    assert cost == Decimal("0.001370")


def test_calculate_cost_unknown_model_zero_cost() -> None:
    """Unknown model should result in zero cost."""
    cost = calculate_cost("unknown/model-xyz", 5000, 2000)
    assert cost == Decimal("0.000000")


def test_calculate_cost_gpt4o_mini() -> None:
    cost = calculate_cost("openai/gpt-4o-mini", 2000, 500)
    # (2000 * 0.00015 + 500 * 0.0006) / 1000 = (0.3 + 0.3) / 1000 = 0.0006
    assert cost == Decimal("0.000600")


# ---------------------------------------------------------------------------
# Integration tests — record_usage_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_event_creates_row_with_cost(
    db_session: AsyncSession,
) -> None:
    """record_usage_event should insert a UsageEvent with calculated cost."""
    org_id = "org-test-001"
    await record_usage_event(
        db_session,
        org_id=org_id,
        api_key_id="key-1",
        pipeline_id=None,
        model="deepseek/deepseek-v4-flash",
        prompt_tokens=500,
        completion_tokens=200,
        latency_ms=123,
    )

    result = await db_session.execute(
        select(UsageEvent).where(UsageEvent.org_id == org_id)
    )
    events = result.scalars().all()
    assert len(events) == 1
    ev = events[0]
    assert ev.prompt_tokens == 500
    assert ev.completion_tokens == 200
    assert ev.latency_ms == 123
    assert ev.model == "deepseek/deepseek-v4-flash"
    expected_cost = calculate_cost("deepseek/deepseek-v4-flash", 500, 200)
    assert ev.cost_usd == expected_cost


@pytest.mark.asyncio
async def test_record_usage_event_unknown_model_zero_cost(
    db_session: AsyncSession,
) -> None:
    """Unknown model should produce zero-cost event but still persist."""
    org_id = "org-test-001"
    await record_usage_event(
        db_session,
        org_id=org_id,
        api_key_id=None,
        pipeline_id=None,
        model="mystery/model-v99",
        prompt_tokens=100,
        completion_tokens=50,
    )

    result = await db_session.execute(
        select(UsageEvent).where(UsageEvent.org_id == org_id)
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].cost_usd == Decimal("0.000000")


# ---------------------------------------------------------------------------
# Integration tests — aggregate_usage_daily
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_usage_daily_creates_summary(
    db_session: AsyncSession,
) -> None:
    """Aggregator should create UsageDaily row from UsageEvents."""
    from ragp_api.workers.tasks import aggregate_usage_daily

    org_id = "org-test-001"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    yesterday_dt = datetime(
        yesterday.year, yesterday.month, yesterday.day, 12, 0, 0, tzinfo=timezone.utc
    )

    # Seed events for yesterday
    for i in range(3):
        ev = UsageEvent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            api_key_id=None,
            pipeline_id=None,
            ts=yesterday_dt,
            model="deepseek/deepseek-v4-flash",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=calculate_cost("deepseek/deepseek-v4-flash", 100, 50),
            latency_ms=100,
        )
        db_session.add(ev)
    await db_session.commit()

    with patch("ragp_api.workers.tasks.async_session") as mock_session_factory:
        # Use the real db_session via context manager mock
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_cm

        await aggregate_usage_daily({})

    result = await db_session.execute(
        select(UsageDaily).where(
            UsageDaily.org_id == org_id,
            UsageDaily.day == yesterday,
        )
    )
    daily_rows = result.scalars().all()
    assert len(daily_rows) == 1
    dr = daily_rows[0]
    assert dr.request_count == 3
    assert dr.total_prompt_tokens == 300
    assert dr.total_completion_tokens == 150


@pytest.mark.asyncio
async def test_aggregate_usage_daily_idempotent(
    db_session: AsyncSession,
) -> None:
    """Running aggregator twice should update, not duplicate."""
    from ragp_api.workers.tasks import aggregate_usage_daily

    org_id = "org-test-001"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    yesterday_dt = datetime(
        yesterday.year, yesterday.month, yesterday.day, 10, 0, 0, tzinfo=timezone.utc
    )

    ev = UsageEvent(
        id=str(uuid.uuid4()),
        org_id=org_id,
        api_key_id=None,
        pipeline_id=None,
        ts=yesterday_dt,
        model="openai/gpt-4o-mini",
        prompt_tokens=200,
        completion_tokens=80,
        cost_usd=calculate_cost("openai/gpt-4o-mini", 200, 80),
        latency_ms=200,
    )
    db_session.add(ev)
    await db_session.commit()

    with patch("ragp_api.workers.tasks.async_session") as mock_session_factory:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_cm

        # Run twice
        await aggregate_usage_daily({})
        await aggregate_usage_daily({})

    result = await db_session.execute(
        select(UsageDaily).where(
            UsageDaily.org_id == org_id,
            UsageDaily.day == yesterday,
            UsageDaily.model == "openai/gpt-4o-mini",
        )
    )
    rows = result.scalars().all()
    # Must not have duplicates
    assert len(rows) == 1
    assert rows[0].request_count == 1


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_summary_returns_aggregates(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/orgs/{id}/usage/summary returns aggregated data."""
    data = await _signup(client, "summary-owner@example.com", org_name="SummaryOrg")
    org_id = data["organization"]["id"]
    await _login(client, "summary-owner@example.com")

    # Seed a daily row directly
    today = date.today()
    daily = UsageDaily(
        id=str(uuid.uuid4()),
        org_id=org_id,
        day=today,
        model="deepseek/deepseek-v4-flash",
        total_prompt_tokens=1000,
        total_completion_tokens=500,
        total_cost_usd=Decimal("0.000820"),
        request_count=5,
    )
    db_session.add(daily)
    await db_session.commit()

    resp = await client.get(f"/api/v1/orgs/{org_id}/usage/summary?days=30")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "days" in body
    assert "total_cost_usd" in body
    # At least one day with our model
    day_entries = body["days"]
    assert len(day_entries) >= 1
    assert any(
        any(m["model"] == "deepseek/deepseek-v4-flash" for m in d["models"])
        for d in day_entries
    )


@pytest.mark.asyncio
async def test_member_can_view_summary_admin_can_view_events(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """member+ can access summary; admin+ can access events."""
    owner_data = await _signup(client, "perm-owner@example.com", org_name="PermOrg")
    org_id = owner_data["organization"]["id"]
    user_id = owner_data["user"]["id"]

    # Ensure user is OrgMember (signup might not add to org_members)
    existing = await db_session.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user_id
        )
    )
    if existing.scalar_one_or_none() is None:
        db_session.add(
            OrgMember(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user_id,
                role="owner",
            )
        )
        await db_session.commit()

    await _login(client, "perm-owner@example.com")

    # Summary — owner (member+) can access
    resp_summary = await client.get(f"/api/v1/orgs/{org_id}/usage/summary")
    assert resp_summary.status_code == 200, resp_summary.text

    # Events — owner (admin+) can access
    resp_events = await client.get(f"/api/v1/orgs/{org_id}/usage/events")
    assert resp_events.status_code == 200, resp_events.text


@pytest.mark.asyncio
async def test_rag_query_failure_does_not_block_response(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Even if DB insert for usage fails, RAG response must still succeed."""
    from ragp_api.db.models import Dataset as DatasetModel

    org_id, raw_key, _user_id = await _seed_org_with_api_key(db_session)

    dataset = DatasetModel(
        id=str(uuid.uuid4()), organization_id=org_id, name="Test DS", source="uploaded"
    )
    db_session.add(dataset)
    await db_session.commit()

    mock_chunks: list[dict[str, Any]] = [
        {
            "id": "c1",
            "text": "answer text",
            "score": 0.9,
            "document_id": "doc1",
            "document_name": "doc.txt",
        }
    ]

    mock_retriever = AsyncMock()
    mock_retriever.retrieve = AsyncMock(return_value=mock_chunks)

    mock_generator = AsyncMock()
    mock_generator.generate = AsyncMock(
        return_value={
            "answer": "some answer",
            "trace": {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        }
    )

    with (
        patch(
            "ragp_api.api.v1.routes_rag.get_plugin",
            side_effect=lambda kind, name: (
                (lambda _p: mock_retriever) if kind == "retriever" else (lambda _p: mock_generator)
            ),
        ),
        patch(
            "ragp_api.api.v1.routes_rag._resolve_embedder",
            new=AsyncMock(return_value=(None, "none")),
        ),
        patch(
            "ragp_api.api.v1.routes_rag.record_usage_event",
            new=AsyncMock(side_effect=Exception("DB exploded")),
        ),
    ):
        resp = await client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"dataset_id": dataset.id, "query": "test?"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "some answer"
