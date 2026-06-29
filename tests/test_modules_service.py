"""Unit tests for the dashboard-modularity service.

Pure-ish logic over a tiny KV table — runs on the fast SQLite path (the JSON
column degrades via with_variant). Covers the fail-safe contract: defaults on
empty/corrupt config, Core always-on, Optional isolation, and Redis caching.
"""
from __future__ import annotations

import json
import logging

import pytest

from vitals.models.app_settings import AppSetting
from vitals.services import modules_service
from vitals.services.modules_service import (
    DEFAULT_STATE,
    REDIS_KEY,
    SETTINGS_KEY,
    ModuleToggleError,
)

pytestmark = pytest.mark.asyncio


async def test_defaults_on_empty_db(db_session):
    """No config row → Core True, Optional False, never raises."""
    state = await modules_service.get_enabled_modules(db_session)
    assert state["weight"] is True
    assert state["garmin"] is True
    assert state["labs"] is True
    assert state["reports"] is True
    assert state["hevy"] is False
    assert state["glp1"] is False
    assert state == DEFAULT_STATE


async def test_core_forced_true_even_if_stored_false(db_session):
    """A stored Core=False must be ignored — Core is locked on."""
    db_session.add(AppSetting(key=SETTINGS_KEY, value={"weight": False, "labs": False, "hevy": True}))
    await db_session.commit()

    state = await modules_service.get_enabled_modules(db_session)
    assert state["weight"] is True
    assert state["labs"] is True
    assert state["hevy"] is True


async def test_set_optional_persists(db_session):
    """Enabling an Optional module persists to the DB."""
    returned = await modules_service.set_module_enabled(db_session, key="hevy", enabled=True)
    await db_session.commit()
    assert returned["hevy"] is True

    fresh = await modules_service.get_enabled_modules(db_session, redis=None)
    assert fresh["hevy"] is True


async def test_toggle_isolation(db_session):
    """Toggling one Optional module leaves the others untouched."""
    await modules_service.set_module_enabled(db_session, key="hevy", enabled=True)
    await modules_service.set_module_enabled(db_session, key="supplements", enabled=True)
    await modules_service.set_module_enabled(db_session, key="hevy", enabled=False)
    await db_session.commit()

    state = await modules_service.get_enabled_modules(db_session, redis=None)
    assert state["hevy"] is False
    assert state["supplements"] is True  # unaffected by the hevy toggle
    assert state["glp1"] is False        # still default


async def test_cannot_disable_core(db_session):
    """Core modules are not toggleable."""
    with pytest.raises(ModuleToggleError):
        await modules_service.set_module_enabled(db_session, key="weight", enabled=False)


async def test_unknown_module_raises(db_session):
    """An unknown key is rejected loudly (Zero Silent Errors)."""
    with pytest.raises(ModuleToggleError):
        await modules_service.set_module_enabled(db_session, key="does_not_exist", enabled=True)


async def test_unknown_keys_dropped(db_session):
    """Stale/unknown stored keys are projected away by the registry."""
    db_session.add(AppSetting(key=SETTINGS_KEY, value={"foobar": True, "hevy": True}))
    await db_session.commit()

    state = await modules_service.get_enabled_modules(db_session, redis=None)
    assert "foobar" not in state
    assert state["hevy"] is True
    assert set(state) == set(DEFAULT_STATE)


async def test_malformed_value_falls_back(db_session, caplog):
    """A non-object value → safe defaults, and the fallback is LOGGED."""
    db_session.add(AppSetting(key=SETTINGS_KEY, value="garbage-not-a-dict"))
    await db_session.commit()

    with caplog.at_level(logging.WARNING):
        state = await modules_service.get_enabled_modules(db_session, redis=None)

    assert state == DEFAULT_STATE
    assert any("not an object" in r.message or "not an object" in r.getMessage() for r in caplog.records)


async def test_redis_cache_is_read_through(db_session, redis):
    """A primed Redis value is served without touching the (empty) DB."""
    await modules_service.prime_cache(redis, {**DEFAULT_STATE, "hevy": True})
    # Sanity: the cache holds JSON we can read back.
    assert json.loads(await redis.get(REDIS_KEY))["hevy"] is True

    state = await modules_service.get_enabled_modules(db_session, redis)
    assert state["hevy"] is True  # came from cache; DB has no row


async def test_get_primes_cache_from_db(db_session, redis):
    """A DB read writes the resolved state through to Redis."""
    db_session.add(AppSetting(key=SETTINGS_KEY, value={"glp1": True}))
    await db_session.commit()

    await modules_service.get_enabled_modules(db_session, redis)

    cached = json.loads(await redis.get(REDIS_KEY))
    assert cached["glp1"] is True
