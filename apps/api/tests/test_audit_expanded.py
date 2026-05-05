"""Tests for expanded audit event coverage: dataset/golden/experiment/billing."""

from __future__ import annotations

import io
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    AuditEvent,
    Chunk,
    Document,
    OrgSubscription,
    Plan,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _signup(
    client: AsyncClient,
    email: str,
    password: str = "s3cr3t!",
    org_name: str | None = None,
) -> dict:
    body: dict = {"email": email, "password": password}
    if org_name:
        body["organization_name"] = org_name
    resp = await client.post("/api/v1/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str = "s3cr3t!") -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _create_dataset(client: AsyncClient, org_id: str, name: str = "AuditDS") -> str:
    resp = await client.post(
        "/api/v1/datasets",
        headers={"X-Organization-Id": org_id},
        json={"name": name, "organization_id": org_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload_document(
    client: AsyncClient,
    dataset_id: str,
    org_id: str,
    content: bytes = b"Hello expanded audit world",
    filename: str = "audit_test.txt",
) -> str:
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"X-Organization-Id": org_id},
        files={"file": (filename, io.BytesIO(content), "text/plain")},
        data={"chunker_name": "recursive-character", "chunker_params": "{}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["document_id"]


def _make_redis_pool_mock() -> MagicMock:
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock())
    pool.aclose = AsyncMock()
    return pool


# ---------------------------------------------------------------------------
# dataset.upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dataset_upload_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """upload_document creates dataset.upload audit with name + size_bytes."""
    data = await _signup(client, "audit_upload_x@example.com", org_name="UploadAuditOrg")
    org_id = data["organization"]["id"]

    dataset_id = await _create_dataset(client, org_id)
    file_bytes = b"Test content for audit upload"
    await _upload_document(client, dataset_id, org_id, content=file_bytes, filename="file.txt")

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "dataset.upload",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "dataset.upload audit event not found"
    assert event.resource_id == dataset_id
    assert event.resource_type == "dataset"
    assert event.metadata_json.get("name") == "file.txt"
    assert event.metadata_json.get("size_bytes") == len(file_bytes)


# ---------------------------------------------------------------------------
# dataset.delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dataset_delete_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """delete_dataset creates dataset.delete audit with resource_id and name."""
    data = await _signup(client, "audit_delete_x@example.com", org_name="DeleteAuditOrg")
    org_id = data["organization"]["id"]

    dataset_id = await _create_dataset(client, org_id, name="ToDelete")

    with patch(
        "ragp_api.api.v1.routes_datasets.delete_raw_documents",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.delete(
            f"/api/v1/datasets/{dataset_id}",
            headers={"X-Organization-Id": org_id},
        )
    assert resp.status_code == 204, resp.text

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "dataset.delete",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "dataset.delete audit event not found"
    assert event.resource_id == dataset_id
    assert event.metadata_json.get("name") == "ToDelete"


# ---------------------------------------------------------------------------
# golden.generate
# ---------------------------------------------------------------------------


_PATCH_DEEPSEEK = "ragp_api.services.golden_qa_generator._call_deepseek"


def _deepseek_mock(question: str = "Q?", answer: str = "A.") -> MagicMock:
    content = json.dumps(
        {
            "choices": [
                {"message": {"content": json.dumps({"question": question, "answer": answer})}}
            ]
        }
    )
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json.loads(content)
    return resp


@pytest.mark.asyncio
async def test_golden_generate_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /datasets/{id}/golden creates golden.generate audit with count."""
    data = await _signup(client, "audit_golden_x@example.com", org_name="GoldenAuditOrg")
    org_id = data["organization"]["id"]
    from ragp_api.db.models import Dataset

    ds_id = str(uuid.uuid4())
    ds = Dataset(id=ds_id, organization_id=org_id, name="audit-gs", source="uploaded")
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        dataset_id=ds_id,
        source_uri="upload://audit.txt",
        status="indexed",
    )
    db_session.add(ds)
    db_session.add(doc)
    await db_session.flush()

    c = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=org_id,
        text="Audit test chunk. " * 30,
    )
    db_session.add(c)
    await db_session.commit()

    with patch(_PATCH_DEEPSEEK, new_callable=AsyncMock, return_value=_deepseek_mock()):
        resp = await client.post(
            f"/api/v1/datasets/{ds_id}/golden",
            headers={"X-Organization-Id": org_id},
            json={"sample_size": 1},
        )
    assert resp.status_code == 201, resp.text
    returned_count = resp.json()["count"]

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "golden.generate",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "golden.generate audit event not found"
    assert event.resource_id == ds_id
    assert event.resource_type == "dataset"
    assert event.metadata_json.get("count") == returned_count


# ---------------------------------------------------------------------------
# experiment.start
# ---------------------------------------------------------------------------

PLUGIN_GRID = {
    "chunkers": [{"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}}],
    "retrievers": [{"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}}],
    "generators": [
        {
            "plugin_kind": "generator",
            "plugin_name": "litellm-generator",
            "params": {"model": "openai/gpt-4o-mini"},
        }
    ],
}


@pytest.mark.asyncio
async def test_experiment_start_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
    organization_id: str,
) -> None:
    """POST /experiments creates experiment.start audit with name + dataset_id."""
    dataset_id = await _create_dataset(client, organization_id, name="ExpAuditDS")
    with patch(
        "ragp_api.api.v1.routes_experiments.enqueue",
        new=AsyncMock(return_value={"job_id": "j", "task_id": "t", "deduplicated": False}),
    ):
        resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "AuditExperiment",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )
    assert resp.status_code == 201, resp.text
    exp_id = resp.json()["id"]

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == organization_id,
            AuditEvent.event_type == "experiment.start",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "experiment.start audit event not found"
    assert event.resource_id == exp_id
    assert event.resource_type == "experiment"
    assert event.metadata_json.get("name") == "AuditExperiment"
    assert event.metadata_json.get("dataset_id") == dataset_id


# ---------------------------------------------------------------------------
# experiment.promote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experiment_promote_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
    organization_id: str,
) -> None:
    """POST /experiments/{id}/promote_to_pipeline creates experiment.promote audit."""
    from ragp_api.db.models import Experiment

    dataset_id = await _create_dataset(client, organization_id, name="PromoteAuditDS")

    winning_nodes = [
        {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}},
    ]

    with patch(
        "ragp_api.api.v1.routes_experiments.enqueue",
        new=AsyncMock(return_value={"job_id": "j", "task_id": "t", "deduplicated": False}),
    ):
        create_resp = await client.post(
            "/api/v1/experiments",
            json={
                "name": "PromoteAuditExp",
                "organization_id": organization_id,
                "dataset_id": dataset_id,
                "plugin_grid": PLUGIN_GRID,
            },
        )
    exp_id = create_resp.json()["id"]

    # Simulate completed experiment via direct DB update
    exp_result = await db_session.execute(select(Experiment).where(Experiment.id == exp_id))
    experiment = exp_result.scalar_one()
    experiment.status = "completed"
    experiment.leaderboard_json = [
        {"nodes": winning_nodes, "metrics": {"composite_score": 0.9}, "composite_score": 0.9}
    ]
    await db_session.commit()

    promote_resp = await client.post(
        f"/api/v1/experiments/{exp_id}/promote_to_pipeline",
        json={"name": "AuditPipeline"},
    )
    assert promote_resp.status_code == 201, promote_resp.text
    pipeline_id = promote_resp.json()["id"]

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == organization_id,
            AuditEvent.event_type == "experiment.promote",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "experiment.promote audit event not found"
    assert event.resource_id == exp_id
    assert event.resource_type == "experiment"
    assert event.metadata_json.get("pipeline_id") == pipeline_id
    assert event.metadata_json.get("pipeline_name") == "AuditPipeline"


# ---------------------------------------------------------------------------
# billing.checkout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_checkout_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /subscription/checkout creates billing.checkout audit."""
    data = await _signup(client, "audit_checkout_x@example.com", org_name="CheckoutAuditOrg")
    org_id = data["organization"]["id"]
    await _login(client, "audit_checkout_x@example.com")

    db_session.add(
        Plan(
            id="personal-audit",
            name="Personal Audit",
            price_rub_monthly=Decimal("100"),
            included_q=1000,
            included_storage_bytes=10 * 1024 * 1024,
            max_users=1,
            rpm_per_key=60,
            allow_overage=False,
            is_active=True,
            sort_order=1,
        )
    )
    await db_session.commit()

    fake_payment_id = str(uuid.uuid4())
    fake_confirmation_url = "https://yookassa.ru/checkout/fake"
    fake_amount_rub = Decimal("100")

    with patch(
        "ragp_api.api.v1.routes_billing.create_payment_rub",
        new_callable=AsyncMock,
        return_value=(fake_payment_id, fake_confirmation_url, fake_amount_rub),
    ):
        resp = await client.post(
            f"/api/v1/orgs/{org_id}/subscription/checkout",
            json={"plan_id": "personal-audit"},
        )
    assert resp.status_code == 200, resp.text

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "billing.checkout",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "billing.checkout audit event not found"
    assert event.resource_id == org_id
    assert event.metadata_json.get("plan_id") == "personal-audit"
    assert "amount_rub" in event.metadata_json


# ---------------------------------------------------------------------------
# billing.subscription_started  (new subscription via webhook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_subscription_started_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """YooKassa webhook for new subscription creates billing.subscription_started audit."""
    org_id = str(uuid.uuid4())
    from ragp_api.db.models import Organization

    db_session.add(Organization(id=org_id, name="WebhookAuditOrg", slug=f"webhook-{org_id[:8]}"))
    db_session.add(
        Plan(
            id="starter-wh",
            name="Starter WH",
            price_rub_monthly=Decimal("50"),
            included_q=500,
            included_storage_bytes=5 * 1024 * 1024,
            max_users=1,
            rpm_per_key=30,
            allow_overage=False,
            is_active=True,
            sort_order=1,
        )
    )
    await db_session.commit()

    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    payload = {
        "event": "payment.succeeded",
        "object": {
            "id": payment_id,
            "status": "succeeded",
            "amount": {"value": "50.00", "currency": "RUB"},
            "metadata": {
                "org_id": org_id,
                "plan_id": "starter-wh",
                "type": "subscription",
            },
        },
    }
    resp = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "billing.subscription_started",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "billing.subscription_started audit event not found"
    assert event.resource_id == org_id
    assert event.metadata_json.get("plan_id") == "starter-wh"
    assert event.metadata_json.get("payment_id") == payment_id


# ---------------------------------------------------------------------------
# billing.plan_switched  (plan change via webhook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_plan_switched_audit_event(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """YooKassa webhook for plan switch creates billing.plan_switched audit."""
    from datetime import UTC, datetime, timedelta

    from ragp_api.db.models import Organization

    org_id = str(uuid.uuid4())
    db_session.add(Organization(id=org_id, name="SwitchAuditOrg", slug=f"switch-{org_id[:8]}"))
    db_session.add(
        Plan(
            id="plan-a-sw",
            name="Plan A Switch",
            price_rub_monthly=Decimal("100"),
            included_q=1000,
            included_storage_bytes=10 * 1024 * 1024,
            max_users=1,
            rpm_per_key=60,
            allow_overage=False,
            is_active=True,
            sort_order=1,
        )
    )
    db_session.add(
        Plan(
            id="plan-b-sw",
            name="Plan B Switch",
            price_rub_monthly=Decimal("200"),
            included_q=5000,
            included_storage_bytes=50 * 1024 * 1024,
            max_users=5,
            rpm_per_key=120,
            allow_overage=True,
            is_active=True,
            sort_order=2,
        )
    )
    # Seed existing active subscription on plan-a
    now = datetime.now(UTC)
    db_session.add(
        OrgSubscription(
            id=str(uuid.uuid4()),
            org_id=org_id,
            plan_id="plan-a-sw",
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=20),
            q_used=0,
            storage_bytes_used=0,
            auto_renew=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    payload = {
        "event": "payment.succeeded",
        "object": {
            "id": payment_id,
            "status": "succeeded",
            "amount": {"value": "200.00", "currency": "RUB"},
            "metadata": {
                "org_id": org_id,
                "plan_id": "plan-b-sw",
                "type": "subscription",
            },
        },
    }
    resp = await client.post(
        "/api/v1/billing/webhook/yookassa",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"

    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == org_id,
            AuditEvent.event_type == "billing.plan_switched",
        )
    )
    event = result.scalar_one_or_none()
    assert event is not None, "billing.plan_switched audit event not found"
    assert event.resource_id == org_id
    assert event.metadata_json.get("plan_id") == "plan-b-sw"
    assert event.metadata_json.get("payment_id") == payment_id
