"""Async engine + session factory (ported from Boxly's ``bot/database.py``).

Installs complementary per-query timeouts on Postgres (server-side
``statement_timeout`` + asyncpg client-side ``command_timeout``) and explicit
pool sizing. Pool kwargs are skipped for SQLite, which uses a singleton-thread
pool and rejects them — that path exists only for the fast test suite.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vitals.config import Config


def create_session_factory(config: Config) -> async_sessionmaker[AsyncSession]:
    timeout_ms = config.db_statement_timeout_ms
    connect_args: dict = {}
    engine_kwargs: dict = {
        "echo": False,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }

    if config.database_url.startswith(("postgresql+asyncpg", "postgresql")):
        connect_args["server_settings"] = {"statement_timeout": str(timeout_ms)}
        connect_args["command_timeout"] = timeout_ms / 1000
        engine_kwargs["pool_size"] = config.db_pool_size
        engine_kwargs["max_overflow"] = config.db_max_overflow
        engine_kwargs["pool_timeout"] = config.db_pool_timeout
        engine_kwargs["pool_recycle"] = config.db_pool_recycle

    engine = create_async_engine(config.database_url, **engine_kwargs)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
