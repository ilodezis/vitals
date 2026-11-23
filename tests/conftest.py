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
os.environ.setdefault("VITALS_MCP_CLIENT_SECRET", "test-mcp-secret")
os.environ.setdefault("VITALS_MCP_REDIRECT_HOSTS", "claude.ai,oauth-redirect.googleusercontent.com")

# Explicitly clear external API credentials to isolate test runs from developer's .env
os.environ["VITALS_GARMIN_EMAIL"] = ""
os.environ["VITALS_GARMIN_PASSWORD"] = ""
os.environ["VITALS_HEVY_API_KEY"] = ""
os.environ["VITALS_OPENROUTER_API_KEY"] = ""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

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
    # NullPool on the Postgres path: pytest-asyncio gives each test its own event
    # loop, and a pooled asyncpg connection opened in a previous loop blows up on
    # reuse ("another operation is in progress") — which silently capped this
    # project at one working integration test per file. Not pooling means every
    # test opens its own connection, which is what we want for a test run anyway.
    TEST_ENGINE = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


def pytest_sessionfinish(session, exitstatus):
    """Dispose the shared engine so the process actually exits.

    aiosqlite runs every connection in its own **non-daemon** worker thread, and
    ``StaticPool`` deliberately keeps one connection open for the whole session
    (that is how an ``:memory:`` database survives between tests). Nothing ever
    closed it, so after the last test two live threads kept the interpreter from
    shutting down: the suite printed its summary and then sat there until
    something killed it — minutes of wall time per run, and the reason every
    invocation had to be wrapped in ``timeout``.

    Two engines can be holding such a thread: this module's ``TEST_ENGINE`` and
    the app's own lazily-built one in ``web.deps`` (any code path that skips the
    dependency override builds it against the same in-memory URL).
    """
    import asyncio
    import threading

    async def _dispose() -> None:
        await TEST_ENGINE.dispose()
        try:
            from web import deps
        except Exception:  # web/ not importable in a pure-core run — nothing to do
            return
        factory = deps._session_factory
        if factory is not None:
            await factory.kw["bind"].dispose()

    asyncio.run(_dispose())

    # Anything still non-daemon here will hang the interpreter the same way, so
    # name it now instead of leaving the next person with a silent 15-minute run.
    stragglers = [
        t.name
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon and t.is_alive()
    ]
    if stragglers:
        print(
            "\nWARNING: non-daemon threads still alive after teardown — this run "
            f"will not exit on its own: {', '.join(stragglers)}"
        )


def pytest_collection_modifyitems(config, items):
    """Skip ``@pytest.mark.integration`` unless pointed at a real Postgres."""
    if "postgresql" in TEST_DATABASE_URL:
        return
    skip_pg = pytest.mark.skip(
        reason="integration test requires Postgres: point VITALS_TEST_DATABASE_URL "
        "at one (scripts/test_postgres.sh does it via Docker; see CONTRIBUTING.md "
        "for the no-Docker route)"
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


@pytest.fixture(autouse=True)
def _reset_runtime_settings():
    """A profile saved in one test lives in the process-wide overlay; clear it so
    the next test reads its own environment again."""
    from vitals import runtime_settings

    runtime_settings.clear()
    yield
    runtime_settings.clear()


_SQLITE_SCHEMA_READY = False


def _empty_every_table(conn) -> None:
    """Delete all rows, children first — the cheap way back to a blank database.

    Dropping and recreating 42 tables costs ~160 ms per test, which was most of
    this suite's wall time. Emptying them is ~15 ms and isolates tests just as
    well: no model uses ``AUTOINCREMENT``, so SQLite hands out ids from 1 again
    once a table is empty.
    """
    for table in reversed(Base.metadata.sorted_tables):
        conn.execute(table.delete())


@pytest_asyncio.fixture
async def db_session():
    global _SQLITE_SCHEMA_READY
    async with TEST_ENGINE.begin() as conn:
        if "sqlite" not in TEST_DATABASE_URL:
            # Postgres runs one connection per test (NullPool), so the schema does
            # not survive between them — keep recreating it there.
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        elif _SQLITE_SCHEMA_READY:
            await conn.run_sync(_empty_every_table)
        else:
            await conn.run_sync(Base.metadata.create_all)
            _SQLITE_SCHEMA_READY = True
    factory = async_sessionmaker(TEST_ENGINE, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


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
async def signals_module_on(db_session):
    """Switch the ``signals`` module on for a bare ``db_session`` test.

    The proactive layer is gated on that module (it is the emergency switch, and
    it defaults **off**), so a service-level test that doesn't go through the
    ``client`` fixture has to set the same thing up the owner does in Settings —
    otherwise ``delivery.send`` correctly refuses to send anything.
    """
    from vitals.services import modules_service

    await modules_service.set_module_enabled(db_session, key="signals", enabled=True)
    await db_session.commit()


@pytest_asyncio.fixture
async def all_modules_on(db_session):
    """Mirror the migration seed for service tests that exercise the full lake.

    Bare ``create_all`` databases intentionally use the fail-safe optional-off
    default. Cross-domain context tests opt into the production-like all-on
    state explicitly so module-gating behavior remains testable elsewhere.
    """
    from vitals.models.app_settings import AppSetting
    from vitals.services.modules_service import MODULE_REGISTRY, SETTINGS_KEY

    await db_session.merge(
        AppSetting(key=SETTINGS_KEY, value={key: True for key in MODULE_REGISTRY})
    )
    await db_session.commit()


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

    # merge(), not add(): another fixture may already have written these rows
    # (``signals_module_on`` does), and a blind insert would collide on the PK.
    await db_session.merge(AppSetting(key=SETTINGS_KEY, value={k: True for k in MODULE_REGISTRY}))
    await db_session.merge(AppSetting(key=LANG_SETTINGS_KEY, value="ru"))
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
