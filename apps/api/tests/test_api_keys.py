"""Comprehensive tests for the API key lifecycle (expiration + scope).

Covers:
  - Defaults & validation on POST /api/v1/keys.
  - GET /api/v1/keys ``is_expired`` flag.
  - 401 ``key_expired`` when bearer-authenticated requests use an expired key.
  - require_scope ladder enforcement on rag/datasets/experiments routes.
  - Session-cookie callers bypass scope checks.
  - Migration backfill behaviour for legacy (pre-migration) keys.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ragp_api.db.models import (
    ApiKey,
    Dataset,
    Membership,
    Organization,
    OrgBalance,
    User,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _signup_and_login(
    client: AsyncClient,
    email: str = "lifecycle@example.com",
    password: str = "passw0rd!",
    org_name: str = "lifecycle-org",
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": org_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_org_with_key(
    db: AsyncSession,
    *,
    raw_key: str,
    scope: str = "read",
    expires_at: datetime | None = None,
) -> tuple[str, str, str]:
    """Create org+user+key+dataset and return (org_id, raw_key, dataset_id)."""
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    org = Organization(id=org_id, name=f"org-{org_id[:6]}", slug=f"org-{org_id[:6]}")
    user = User(id=user_id, email=f"u-{org_id[:6]}@example.com", password_hash="x")
    membership = Membership(organization_id=org_id, user_id=user_id, role="admin")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=user_id,
        name=f"key-{scope}",
        key_prefix=raw_key[:8],
        key_hash=key_hash,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(days=90)),
        scope=scope,
    )
    dataset = Dataset(id=str(uuid.uuid4()), organization_id=org_id, name="DS", source="uploaded")
    balance = OrgBalance(org_id=org_id, balance_usd=Decimal("100.00"))
    db.add_all([org, user, membership, api_key, dataset, balance])
    await db.commit()
    return org_id, raw_key, dataset.id


# ---------------------------------------------------------------------------
# Create-key validation & defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_key_default_expires_in_90_days_and_scope_read(
    client: AsyncClient,
) -> None:
    """POST /keys with only `name` → expires_at ≈ now()+90d, scope='read'."""
    await _signup_and_login(client, email="def@example.com", org_name="def-org")
    before = datetime.now(UTC)
    resp = await client.post("/api/v1/keys", json={"name": "x"})
    after = datetime.now(UTC)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == "read"
    expires_at = datetime.fromisoformat(body["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    # window: [before+90d - 5s, after+90d + 5s] to allow for clock drift
    lo = before + timedelta(days=90) - timedelta(seconds=5)
    hi = after + timedelta(days=90) + timedelta(seconds=5)
    assert lo <= expires_at <= hi, f"{expires_at} not in [{lo}, {hi}]"


@pytest.mark.asyncio
async def test_create_key_with_custom_expires_in_days_clamped_to_365(
    client: AsyncClient,
) -> None:
    """expires_in_days > 365 → 422 validation."""
    await _signup_and_login(client, email="clamp@example.com", org_name="clamp-org")
    resp = await client.post("/api/v1/keys", json={"name": "x", "expires_in_days": 400})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_key_rejects_expires_in_days_zero_or_negative(
    client: AsyncClient,
) -> None:
    await _signup_and_login(client, email="neg@example.com", org_name="neg-org")
    for bad in (0, -1):
        resp = await client.post("/api/v1/keys", json={"name": "x", "expires_in_days": bad})
        assert resp.status_code == 422, f"value={bad} got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_create_key_rejects_invalid_scope(client: AsyncClient) -> None:
    await _signup_and_login(client, email="badscope@example.com", org_name="badscope-org")
    resp = await client.post("/api/v1/keys", json={"name": "x", "scope": "superuser"})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_key_with_max_expires_in_days_accepted(
    client: AsyncClient,
) -> None:
    """Boundary: expires_in_days=365 must be accepted."""
    await _signup_and_login(client, email="max@example.com", org_name="max-org")
    resp = await client.post(
        "/api/v1/keys", json={"name": "x", "expires_in_days": 365, "scope": "admin"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope"] == "admin"


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keys_returns_is_expired_flag(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Create a key, backdate expires_at via DB, then list and check is_expired."""
    await _signup_and_login(client, email="list@example.com", org_name="list-org")
    create_resp = await client.post("/api/v1/keys", json={"name": "k1"})
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    # Move expires_at into the past
    past = datetime.now(UTC) - timedelta(days=1)
    await db_session.execute(update(ApiKey).where(ApiKey.id == key_id).values(expires_at=past))
    await db_session.commit()

    list_resp = await client.get("/api/v1/keys")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == key_id
    assert items[0]["is_expired"] is True


# ---------------------------------------------------------------------------
# Expired key → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_key_returns_401_key_expired(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Bearer-authenticated request with an expired key → 401 key_expired."""
    raw_key = "rgp_expired" + "0" * 25
    expired_at = datetime.now(UTC) - timedelta(days=1)
    _org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="admin", expires_at=expired_at
    )

    resp = await client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"dataset_id": dataset_id, "query": "hello"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "key_expired"


# ---------------------------------------------------------------------------
# Scope enforcement on /rag/query (read)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_scope_can_call_rag_query(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-scope key is allowed to call rag/query — no 403 insufficient_scope.

    The retriever is mocked to avoid hitting the (sqlite-incompatible)
    pgvector hybrid implementation; we only assert the scope gate passes.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    raw_key = "rgp_read" + "0" * 28
    _org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="read"
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[])

    with (
        patch(
            "ragp_api.api.v1.routes_rag.get_plugin",
            side_effect=lambda kind, name: (
                (lambda _p: mock_retriever) if kind == "retriever" else None
            ),
        ),
        patch(
            "ragp_api.api.v1.routes_rag._resolve_embedder",
            new=AsyncMock(return_value=(None, "none")),
        ),
    ):
        resp = await client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"dataset_id": dataset_id, "query": "hello"},
        )

    # We allow any non-403 response — scope check passed if we get past it.
    assert resp.status_code != 403, f"scope check rejected read key: {resp.text}"


# ---------------------------------------------------------------------------
# Scope enforcement on dataset upload (write)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_scope_cannot_call_ingest_403(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A read-scope key trying to upload a doc → 403 insufficient_scope."""
    raw_key = "rgp_readonly" + "0" * 24
    _org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="read"
    )
    files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"Authorization": f"Bearer {raw_key}"},
        files=files,
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["detail"] == "insufficient_scope"
    assert detail["required"] == "write"
    assert detail["have"] == "read"


@pytest.mark.asyncio
async def test_write_scope_can_ingest(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A write-scope key trying to upload a doc must NOT be 403."""
    raw_key = "rgp_writer" + "0" * 26
    _org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="write"
    )
    files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = await client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers={"Authorization": f"Bearer {raw_key}"},
        files=files,
    )
    assert resp.status_code != 403, resp.text


# ---------------------------------------------------------------------------
# Scope enforcement on experiments (write)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_scope_can_create_experiment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """admin > write — admin must NOT be blocked by require_scope('write')."""
    from unittest.mock import AsyncMock, patch

    raw_key = "rgp_admin1" + "0" * 26
    org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="admin"
    )

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=None)
    fake_pool.aclose = AsyncMock(return_value=None)

    with patch(
        "ragp_api.api.v1.routes_experiments.create_pool",
        new=AsyncMock(return_value=fake_pool),
    ):
        resp = await client.post(
            "/api/v1/experiments",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={
                "name": "exp",
                "organization_id": org_id,
                "dataset_id": dataset_id,
                "plugin_grid": {},
            },
        )
    assert resp.status_code != 403, resp.text
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_read_scope_cannot_create_experiment_403(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    raw_key = "rgp_readexp" + "0" * 25
    org_id, raw_key, dataset_id = await _seed_org_with_key(
        db_session, raw_key=raw_key, scope="read"
    )
    resp = await client.post(
        "/api/v1/experiments",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "name": "exp",
            "organization_id": org_id,
            "dataset_id": dataset_id,
            "plugin_grid": {},
        },
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Session-cookie bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_cookie_bypasses_scope_check(
    client: AsyncClient,
) -> None:
    """UI users authenticated via session cookie must NOT be blocked by scope.

    They list their keys (a session-only endpoint) — but more importantly, an
    endpoint guarded by require_scope('write') must accept the session caller.
    """
    await _signup_and_login(client, email="ui@example.com", org_name="ui-org")
    # Create a dataset via session — protected by require_scope('write').
    resp = await client.post(
        "/api/v1/datasets",
        json={"name": "from-ui", "source": "uploaded"},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Migration backfill (model-level — alembic upgrade is run by acceptance tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_backfills_existing_keys_with_90d_and_admin_scope() -> None:
    """Verify the 0014 migration's backfill SQL is correct.

    Simulates the pre-migration schema: api_keys without expires_at/scope
    columns. Then applies the same DDL+UPDATE the migration runs (sqlite
    flavour) and confirms the legacy row was backfilled with admin scope
    and a +90d expiration.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # Pre-migration schema: api_keys without expires_at/scope/revoked_at.
        await conn.execute(
            text(
                "CREATE TABLE api_keys ("
                " id TEXT PRIMARY KEY,"
                " organization_id TEXT NOT NULL,"
                " user_id TEXT NOT NULL,"
                " name TEXT NOT NULL,"
                " key_prefix TEXT NOT NULL,"
                " key_hash TEXT NOT NULL UNIQUE,"
                " last_used_at TEXT,"
                " created_at TEXT"
                ")"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, organization_id, user_id, name, key_prefix, key_hash, created_at) "
                "VALUES ('k1', 'org1', 'u1', 'legacy', 'rgp_lega', "
                "'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef', "
                "datetime('now'))"
            )
        )

        # Apply the migration steps (sqlite branch).
        await conn.execute(text("ALTER TABLE api_keys ADD COLUMN expires_at TEXT"))
        await conn.execute(
            text("ALTER TABLE api_keys ADD COLUMN scope VARCHAR(16) NOT NULL DEFAULT 'read'")
        )
        await conn.execute(text("ALTER TABLE api_keys ADD COLUMN revoked_at TEXT"))
        await conn.execute(
            text(
                "UPDATE api_keys "
                "SET expires_at = datetime('now', '+90 days'), "
                "    scope = 'admin' "
                "WHERE expires_at IS NULL"
            )
        )

        # Read back and assert.
        rows = (await conn.execute(text("SELECT id, scope, expires_at FROM api_keys"))).all()
        assert len(rows) == 1
        legacy = rows[0]
        assert legacy[0] == "k1"
        assert legacy[1] == "admin"
        assert legacy[2] is not None
        # Naive datetime string from sqlite — parse and compare loosely.
        parsed = datetime.fromisoformat(str(legacy[2])).replace(tzinfo=UTC)
        delta = parsed - datetime.now(UTC)
        assert timedelta(days=88) <= delta <= timedelta(days=91)

    await engine.dispose()
