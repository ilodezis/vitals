import asyncio
import os
import sys

# Set up local testing environment variables
os.environ["VITALS_DATABASE_URL"] = "sqlite+aiosqlite:///local_vitals.db"
os.environ["VITALS_REDIS_URL"] = "redis://localhost:6379/0"
os.environ["VITALS_TIMEZONE"] = "Europe/Chisinau"
os.environ["VITALS_SESSION_SECRET"] = "local-secret-key-1234567890"
os.environ["VITALS_AUTH_USERNAME"] = "timur"
# bcrypt hash of "password"
os.environ["VITALS_AUTH_PASSWORD_HASH"] = "$2b$04$V2PTdRXGL2bhQbX8frCBeuQp8X01Cj84UQCRKDsVNGAOU/siMDlha"
os.environ["VITALS_COOKIE_SECURE"] = "false"
os.environ["VITALS_MCP_CLIENT_SECRET"] = "local-test-mcp-secret"
# Real Claude.ai callback (so a real connector can be tested against localhost via
# a tunnel) plus a fake local one for manual curl/browser checks of the OAuth flow.
os.environ["VITALS_MCP_REDIRECT_URIS"] = (
    "https://claude.ai/api/mcp/auth_callback,http://127.0.0.1:8000/callback"
)

import fakeredis.aioredis
import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vitals.models.base import Base

# Patch get_redis_client to return FakeRedis
import web.deps
web.deps._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

async def init_db(database_url: str | None = None):
    """Rebuild the disposable local DB and load the current UI demo dataset."""
    engine = create_async_engine(database_url or os.environ["VITALS_DATABASE_URL"])
    async with engine.begin() as conn:
        # local_vitals.db is a disposable browser fixture, not user data. Rebuild
        # it so old SQLite files also receive columns added by newer features.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from scripts.seed_demo import seed_all

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        counts = await seed_all(session)
        await session.commit()
    await engine.dispose()

    print("Local database rebuilt and seeded with current demo data")
    print("Seeded: " + ", ".join(f"{name}={count}" for name, count in counts.items()))

if __name__ == "__main__":
    asyncio.run(init_db())
    print("Starting local server on http://127.0.0.1:8000")
    print("Username: timur, Password: password")
    uvicorn.run("web.main:app", host="127.0.0.1", port=8000, reload=False)
