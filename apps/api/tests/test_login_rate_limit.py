"""Tests for brute-force rate limiting on POST /api/v1/auth/login."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient

from ragp_api.db.redis import get_redis
from ragp_api.main import app
from ragp_api.settings import settings as _settings


async def _signup(
    client: AsyncClient,
    email: str,
    password: str = "correct-horse-battery!",
) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "organization_name": None},
    )
    assert resp.status_code == 201, resp.text
    # Drop the session cookie set by signup so subsequent /login calls behave
    # like a fresh client without authenticated state.
    client.cookies.clear()


@pytest.mark.asyncio
async def test_login_first_attempts_pass(client: AsyncClient) -> None:
    """The first N wrong-password attempts must return 401, never 429."""
    email = "rl-first@example.com"
    await _signup(client, email=email)

    original_limit = _settings.login_rate_limit_attempts
    _settings.login_rate_limit_attempts = 5
    try:
        for i in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong!"},
            )
            assert resp.status_code == 401, f"Attempt {i + 1}: {resp.status_code} {resp.text}"
    finally:
        _settings.login_rate_limit_attempts = original_limit


@pytest.mark.asyncio
async def test_login_6th_attempt_blocked_429(client: AsyncClient) -> None:
    """The (limit+1)-th attempt must return 429 with a Retry-After header."""
    email = "rl-sixth@example.com"
    await _signup(client, email=email)

    original_limit = _settings.login_rate_limit_attempts
    _settings.login_rate_limit_attempts = 5
    try:
        for _ in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong!"},
            )
            assert resp.status_code == 401

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong!"},
        )
        assert resp.status_code == 429, resp.text
        assert resp.json()["detail"] == "too_many_login_attempts"
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1
    finally:
        _settings.login_rate_limit_attempts = original_limit


@pytest.mark.asyncio
async def test_login_rate_limit_per_email(client: AsyncClient) -> None:
    """Two different emails from the same IP must have independent counters."""
    email_a = "rl-a@example.com"
    email_b = "rl-b@example.com"
    await _signup(client, email=email_a)
    await _signup(client, email=email_b)

    original_limit = _settings.login_rate_limit_attempts
    _settings.login_rate_limit_attempts = 3
    try:
        # Exhaust counter for email_a.
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email_a, "password": "wrong!"},
            )
            assert resp.status_code == 401
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email_a, "password": "wrong!"},
        )
        assert resp.status_code == 429

        # email_b must still accept attempts (separate counter).
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email_b, "password": "wrong!"},
        )
        assert resp.status_code == 401, resp.text
    finally:
        _settings.login_rate_limit_attempts = original_limit


@pytest.mark.asyncio
async def test_login_rate_limit_per_ip_via_xff(client: AsyncClient) -> None:
    """Different X-Forwarded-For IPs for the same email must not share counter."""
    email = "rl-xff@example.com"
    await _signup(client, email=email)

    original_limit = _settings.login_rate_limit_attempts
    _settings.login_rate_limit_attempts = 2
    try:
        # IP #1 — exhaust.
        for _ in range(2):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong!"},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert resp.status_code == 401
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong!"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert resp.status_code == 429

        # IP #2 — fresh counter.
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong!"},
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        assert resp.status_code == 401, resp.text
    finally:
        _settings.login_rate_limit_attempts = original_limit


@pytest.mark.asyncio
async def test_login_success_does_not_reset_counter(client: AsyncClient) -> None:
    """A successful login must not clear earlier failed attempts."""
    email = "rl-success@example.com"
    password = "right-pass-1!"
    await _signup(client, email=email, password=password)

    original_limit = _settings.login_rate_limit_attempts
    _settings.login_rate_limit_attempts = 4
    try:
        # Burn 3 failed attempts (one slot left in the window).
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong!"},
            )
            assert resp.status_code == 401

        # Successful login uses the 4th slot but does not reset history.
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        client.cookies.clear()

        # Next attempt must be blocked — counter was not reset by the success.
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-again!"},
        )
        assert resp.status_code == 429, resp.text
        assert resp.json()["detail"] == "too_many_login_attempts"
    finally:
        _settings.login_rate_limit_attempts = original_limit


@pytest.mark.asyncio
async def test_login_rate_limit_redis_down_fail_open(client: AsyncClient) -> None:
    """If Redis raises, login must fall through to normal auth (fail-open)."""
    email = "rl-redisdown@example.com"
    password = "ok-pass-1!"
    await _signup(client, email=email, password=password)

    class _BrokenRedis:
        def pipeline(self) -> Any:
            raise ConnectionError("Redis is down")

    async def override_get_redis() -> AsyncIterator[_BrokenRedis]:
        yield _BrokenRedis()

    app.dependency_overrides[get_redis] = override_get_redis
    # Wrong password still gets 401, not 429 — limiter failed open.
    for _ in range(10):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong!"},
        )
        assert resp.status_code == 401, resp.text

    # Correct password still works.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
