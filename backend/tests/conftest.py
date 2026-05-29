"""
Shared pytest fixtures for the Centras Tokenizer test suite.

Strategy
--------
- Use an in-memory SQLite database (aiosqlite) so tests are isolated and fast.
- Override `get_db` via FastAPI dependency_overrides per test.
- Override `get_settings` by clearing the lru_cache and returning a
  test-specific Settings object, so every module that calls get_settings()
  during request handling receives test values.
- Provide a pre-minted JWT token fixture so auth-protected tests stay concise.

Important: the FastAPI app module is imported once at session scope; the
dependency override on `get_db` routes every request through the per-test
in-memory session so rows are rolled back after each test.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Test credentials (same as defaults in config.py; stated explicitly here so
# tests don't depend on file-system .env values)
# ---------------------------------------------------------------------------
TEST_JWT_SECRET = "test-secret-key-32-chars-long-xx"
TEST_JWT_ALGORITHM = "HS256"
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "centras_admin_2024"


def _make_test_settings():
    """Instantiate Settings with deterministic test values, bypassing .env."""
    # Import here (not at module level) to avoid triggering lru_cache before
    # we have a chance to clear it.
    from app.config import Settings

    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key=TEST_JWT_SECRET,
        jwt_algorithm=TEST_JWT_ALGORITHM,
        jwt_expire_minutes=60,
        admin_username=TEST_ADMIN_USERNAME,
        admin_password=TEST_ADMIN_PASSWORD,
        gemini_api_key="",          # No real key → mock mode in Gemini tests
        gemini_model="gemini-1.5-flash",
        environment="test",
        cors_origins_raw="http://localhost:3000",
        rate_limit_per_minute=10000,  # effectively disable rate limiting in tests
    )


# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine — StaticPool keeps the single ":memory:"
# connection alive for the whole session so tables created once are visible
# to every session opened against the same engine.
# ---------------------------------------------------------------------------
TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(
    bind=TEST_ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Session-scoped: create DB tables once, tear them down after all tests.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """A single event loop shared by all async tests in the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_db_tables():
    """
    Create all ORM tables against the shared in-memory engine before any test
    runs.  Importing `app.models` registers every SQLAlchemy model with Base.
    """
    from app.database import Base
    import app.models  # noqa: F401 — side-effect: registers ORM models

    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Per-test: fresh session rolled back after each test for isolation.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session that is rolled back after each test, keeping
    the in-memory DB clean between tests.
    """
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Settings fixture — exposes test settings to individual tests.
# ---------------------------------------------------------------------------

@pytest.fixture()
def settings():
    """Test-mode Settings instance."""
    return _make_test_settings()


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_jwt_token() -> str:
    """Mint a fresh JWT for the test admin user using the test secret."""
    payload = {
        "sub": TEST_ADMIN_USERNAME,
        "exp": datetime.utcnow() + timedelta(minutes=60),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


@pytest.fixture()
def auth_headers(valid_jwt_token: str) -> dict[str, str]:
    """Authorization header dict ready to pass to HTTPX requests."""
    return {"Authorization": f"Bearer {valid_jwt_token}"}


# ---------------------------------------------------------------------------
# HTTPX async test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTPX client wired to the FastAPI application.

    Per-request the following are overridden:
    - `get_db`       → yields the per-test `db_session` (in-memory, rolled back after each test)
    - `get_settings` → returns the test Settings object (no .env file read,
                       lru_cache cleared so the patch is picked up everywhere)

    All other behaviour — middlewares, routers, exception handlers — runs
    exactly as in production, keeping the integration test realistic.
    """
    from app.main import app as fastapi_app
    from app.database import get_db
    import app.config as config_module

    test_settings = _make_test_settings()

    async def override_get_db():
        yield db_session

    # Clear lru_cache so the patched get_settings is seen by all callers.
    config_module.get_settings.cache_clear()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    with patch.object(config_module, "get_settings", return_value=test_settings):
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    fastapi_app.dependency_overrides.pop(get_db, None)
    # Restore lru_cache behaviour for subsequent tests.
    config_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Convenience data builders (available as fixtures and as plain functions)
# ---------------------------------------------------------------------------

def make_ohlcv_candles(n: int = 20) -> list[dict]:
    """
    Return n synthetic OHLCV candle dicts with a gentle uptrend.
    Suitable for seeding the DB or direct tokenizer input.
    """
    base_price = 100.0
    start = datetime(2024, 1, 1, 9, 0, 0)
    candles = []
    for i in range(n):
        close = base_price + i * 0.5 + (i % 3) * 0.1
        candles.append(
            {
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000_000.0 + i * 5_000,
                "timestamp": start + timedelta(days=i),
            }
        )
    return candles


@pytest.fixture()
def sample_candles() -> list[dict]:
    """20 synthetic OHLCV candles as a pytest fixture."""
    return make_ohlcv_candles(20)


@pytest.fixture()
def flat_candles() -> list[dict]:
    """10 candles with identical close price — edge-case for std=0 guard."""
    start = datetime(2024, 1, 1)
    return [
        {
            "open": 50.0,
            "high": 50.5,
            "low": 49.5,
            "close": 50.0,
            "volume": 500_000.0,
            "timestamp": start + timedelta(days=i),
        }
        for i in range(10)
    ]
