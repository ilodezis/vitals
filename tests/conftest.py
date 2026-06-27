"""Shared test fixtures (shaped like Boxly's conftest).

Defaults to throwaway in-memory SQLite; point ``VITALS_TEST_DATABASE_URL`` at a
real Postgres (``scripts/test_postgres.sh`` does this) to exercise what SQLite
fakes — JSONB / GIN / partial-unique indexes, ``func.date`` semantics — which is
where this schema actually lives. ``@pytest.mark.integration`` tests are skipped
on SQLite.
"""
import os

# Set before importing app modules so config/security read test values.
os.environ.setdefault("VITALS_TESTING", "1")
os.environ.setdefault("VITALS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("VITALS_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("VITALS_TIMEZONE", "Europe/Chisinau")
os.environ.setdefault("VITALS_HEIGHT_CM", "190")
os.environ.setdefault("VITALS_SEX", "male")
os.environ.setdefault("VITALS_SESSION_SECRET", "test-session-secret")
os.environ.setdefault("VITALS_AUTH_USERNAME", "tester")
# bcrypt hash of "password" (4 rounds — fast test cost).
os.environ.setdefault(
    "VITALS_AUTH_PASSWORD_HASH",
    "$2b$04$V2PTdRXGL2bhQbX8frCBeuQp8X01Cj84UQCRKDsVNGAOU/siMDlha",
)
os.environ.setdefault("VITALS_COOKIE_SECURE", "false")

# Explicitly clear external API credentials to isolate test runs from developer's .env
os.environ["VITALS_GARMIN_EMAIL"] = ""
os.environ["VITALS_GARMIN_PASSWORD"] = ""
os.environ["VITALS_HEVY_API_KEY"] = ""
os.environ["VITALS_OPENROUTER_API_KEY"] = ""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import vitals.models  # noqa: F401 — register all tables on Base.metadata
from vitals.models.base import Base

TEST_USERNAME = "tester"
TEST_PASSWORD = "password"

TEST_DATABASE_URL = os.getenv(
    "VITALS_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:"
)

if "sqlite" in TEST_DATABASE_URL:
    TEST_ENGINE = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
else:
    TEST_ENGINE = create_async_engine(TEST_DATABASE_URL)


def pytest_collection_modifyitems(config, items):
    """Skip ``@pytest.mark.integration`` unless pointed at a real Postgres."""
    if "postgresql" in TEST_DATABASE_URL:
        return
    skip_pg = pytest.mark.skip(
        reason="integration test requires Postgres (run scripts/test_postgres.sh)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_pg)


@pytest.fixture(autouse=True)
def _reset_engine_registries():
    """Keep module-level registries (conflict resolvers, scheduler jobs) isolated
    between tests."""
    from vitals.services import conflict_engine
    from vitals.scheduler import scheduler as scheduler_mod

    conflict_engine.clear_domain_resolvers()
    scheduler_mod.clear_jobs()
    yield
    conflict_engine.clear_domain_resolvers()
    scheduler_mod.clear_jobs()


@pytest_asyncio.fixture
async def db_session():
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(TEST_ENGINE, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session_factory(db_session):
    """Fake session factory delegating to the same db_session used in tests."""

    class _CM:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_):
            pass

    class _Factory:
        def __call__(self):
            return _CM()

    return _Factory()


@pytest_asyncio.fixture
async def redis():
    """In-memory fakeredis client (async)."""
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def client(db_session, redis):
    """FastAPI AsyncClient pointing at the root app with dependency overrides."""
    from web.main import app
    from web.deps import get_session, get_redis

    # Seed all dashboard modules ON so Optional pages are reachable in web tests —
    # mirrors the 0012 migration seed (create_all doesn't run migrations, and the
    # fail-safe default is Optional OFF, which would otherwise hide/redirect them).
    from vitals.models.app_settings import AppSetting
    from vitals.services.modules_service import MODULE_REGISTRY, SETTINGS_KEY
    from vitals.services.language_service import SETTINGS_KEY as LANG_SETTINGS_KEY

    db_session.add(AppSetting(key=SETTINGS_KEY, value={k: True for k in MODULE_REGISTRY}))
    db_session.add(AppSetting(key=LANG_SETTINGS_KEY, value="ru"))
    await db_session.commit()

    async def _get_session():
        yield db_session

    async def _get_redis():
        return redis

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_redis] = _get_redis

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client):
    """An authenticated AsyncClient using credentials from the test env."""
    # TEST_USERNAME/TEST_PASSWORD are module-level globals; reference them directly
    # rather than re-importing `tests.conftest` (which a site-packages `tests`
    # package can shadow, breaking the import).
    r = await client.post("/login", data={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    assert r.status_code == 303
    return client

