import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ragp_api.db import models  # noqa: F401 — ensure models are registered
from ragp_api.db.base import Base
from ragp_api.db.redis import get_redis
from ragp_api.deps import get_db
from ragp_api.main import app
from ragp_api.plugins.registry import _registry, bootstrap
from ragp_api.settings import settings

# If TEST_DATABASE_URL is provided (e.g. in CI with real postgres), use it.
# Otherwise fall back to in-memory SQLite for quick local runs.
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_IS_POSTGRES = _TEST_DB_URL.startswith("postgresql")


@pytest_asyncio.fixture(autouse=True)
async def reset_registry():
    """Clear plugin registry before each test to avoid cross-test pollution."""
    old_enforce_subscription_quotas = settings.enforce_subscription_quotas
    old_allow_legacy_org_header = settings.allow_legacy_org_header
    old_yookassa_require_ip_check = settings.yookassa_require_ip_check
    old_yookassa_revalidate_payment = settings.yookassa_revalidate_payment
    settings.enforce_subscription_quotas = False
    settings.allow_legacy_org_header = True
    # Tests target the public webhook with synthetic payloads — bypass the
    # production IP allowlist + payment re-validation by default.  Individual
    # test modules opt back in by toggling these flags inside the test body.
    settings.yookassa_require_ip_check = False
    settings.yookassa_revalidate_payment = False
    _registry.clear()
    bootstrap()
    yield
    settings.enforce_subscription_quotas = old_enforce_subscription_quotas
    settings.allow_legacy_org_header = old_allow_legacy_org_header
    settings.yookassa_require_ip_check = old_yookassa_require_ip_check
    settings.yookassa_revalidate_payment = old_yookassa_revalidate_payment
    _registry.clear()


@pytest_asyncio.fixture
async def db_engine():
    from sqlalchemy import text

    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        if _IS_POSTGRES:
            # pgvector extension must exist before create_all so that
            # the Vector column type is recognised by Postgres.
            await conn.execute(
                __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
            )
        await conn.run_sync(Base.metadata.create_all)
        # Seed the canonical test organisations that tests reference via
        # X-Organization-Id or the `organization_id` fixture.  PostgreSQL
        # enforces FK constraints (SQLite does not), so the rows must exist
        # before any Dataset / Document / Experiment can reference them.
        if _IS_POSTGRES:
            await conn.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) VALUES "
                    "('org-test-001', 'Test Org', 'test-org'), "
                    "('other-org', 'Other Org', 'other-org') "
                    "ON CONFLICT (id) DO NOTHING"
                )
            )
        else:
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO organizations (id, name, slug) VALUES "
                    "('org-test-001', 'Test Org', 'test-org')"
                )
            )
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO organizations (id, name, slug) VALUES "
                    "('other-org', 'Other Org', 'other-org')"
                )
            )
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    fake_redis = FakeRedis()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_redis() -> AsyncIterator[FakeRedis]:
        yield fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await fake_redis.aclose()


@pytest.fixture
def organization_id() -> str:
    return "org-test-001"
