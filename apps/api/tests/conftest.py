import os
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ragp_api.db import models  # noqa: F401 — ensure models are registered
from ragp_api.db.base import Base
from ragp_api.deps import get_db
from ragp_api.main import app
from ragp_api.plugins.registry import _registry, bootstrap

# If TEST_DATABASE_URL is provided (e.g. in CI with real postgres), use it.
# Otherwise fall back to in-memory SQLite for quick local runs.
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_IS_POSTGRES = _TEST_DB_URL.startswith("postgresql")


@pytest_asyncio.fixture(autouse=True)
async def reset_registry():
    """Clear plugin registry before each test to avoid cross-test pollution."""
    _registry.clear()
    bootstrap()
    yield
    _registry.clear()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        if _IS_POSTGRES:
            # pgvector extension must exist before create_all so that
            # the Vector column type is recognised by Postgres.
            await conn.execute(
                __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
            )
        await conn.run_sync(Base.metadata.create_all)
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

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def organization_id() -> str:
    return "org-test-001"


@pytest_asyncio.fixture(autouse=True)
async def seed_test_organization(db_engine: Any) -> None:
    """Ensure the stub org 'org-test-001' exists in the DB before each test.

    PostgreSQL enforces FK constraints (SQLite does not), so any
    Dataset/Document/etc. that references organization_id='org-test-001'
    needs the row to exist first. This fixture upserts it safely.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    if _IS_POSTGRES:
        insert_sql = (
            "INSERT INTO organizations (id, name, slug) "
            "VALUES ('org-test-001', 'Test Org', 'test-org') "
            "ON CONFLICT (id) DO NOTHING"
        )
    else:
        # SQLite upsert syntax
        insert_sql = (
            "INSERT OR IGNORE INTO organizations (id, name, slug) "
            "VALUES ('org-test-001', 'Test Org', 'test-org')"
        )
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(text(insert_sql))
        await session.commit()
