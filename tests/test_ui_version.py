"""Tests for the UI-version toggle (classic | masthead).

Service-level tests mirror how ``language_service`` behaves — DB is the source of
truth, Redis a read-through cache, safe-default on anything unexpected. The
route/render tests mirror ``test_settings`` / ``test_i18n`` and assert the frame
actually swaps between the classic navbar and the masthead rail.
"""
from __future__ import annotations

import pytest

from vitals.models.app_settings import AppSetting
from vitals.services import ui_version_service as svc

pytestmark = pytest.mark.asyncio


# ── Service ───────────────────────────────────────────────────────────────────


async def test_default_is_classic(db_session, redis):
    """No row → the safe default, so the frame always renders."""
    assert await svc.get_ui_version(db_session, redis) == "classic"


async def test_set_and_get_masthead(db_session, redis):
    result = await svc.set_ui_version(db_session, "masthead", redis)
    await db_session.commit()
    assert result == "masthead"

    # Persisted to app_settings (a single row — no migration/new table).
    row = await db_session.get(AppSetting, svc.SETTINGS_KEY)
    assert row is not None and row.value == "masthead"

    # Write-through to Redis, and read back resolves to masthead.
    assert await redis.get(svc.REDIS_KEY) == "masthead"
    assert await svc.get_ui_version(db_session, redis) == "masthead"


async def test_invalid_value_falls_back_to_default(db_session, redis):
    result = await svc.set_ui_version(db_session, "nonsense", redis)
    assert result == "classic"
    assert await svc.get_ui_version(db_session, redis) == "classic"


async def test_redis_read_through(db_session, redis):
    """A primed cache is honoured without hitting the DB row."""
    await svc.prime_cache(redis, "masthead")
    assert await svc.get_ui_version(db_session, redis) == "masthead"


# ── Route + render ────────────────────────────────────────────────────────────


async def test_ui_version_route_redirects(auth_client):
    r = await auth_client.post("/settings/ui-version", data={"ui_version": "masthead"})
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?saved=ui_version"


async def test_masthead_swaps_the_frame(auth_client):
    """After switching, pages render the rail + .ui-masthead body and drop the
    classic navbar — and back again."""
    await auth_client.post("/settings/ui-version", data={"ui_version": "masthead"})
    r = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "ui-masthead" in r.text
    assert 'id="primary-nav-masthead"' in r.text
    assert 'id="primary-nav"' not in r.text

    # Switching back restores the classic navbar.
    await auth_client.post("/settings/ui-version", data={"ui_version": "classic"})
    r = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'id="primary-nav"' in r.text
    assert 'id="primary-nav-masthead"' not in r.text


async def test_classic_is_the_default_render(auth_client):
    """A session with no ui_version row renders the classic navbar."""
    r = await auth_client.get("/weight", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'id="primary-nav"' in r.text
    assert 'id="primary-nav-masthead"' not in r.text


async def test_masthead_rubric_number_is_stable_per_rubric(auth_client):
    """The eyebrow's "Раздел NN" must track the rubric's own position (Health=01,
    Markers=02, Lifestyle=03) — not the position of whichever tab is active inside
    it. Regression test: it used to reuse the tab's index within its rubric, so
    switching tabs (Вес/Организм/Отчёты, all "Health") changed the number, and
    unrelated rubrics could show the same number by coincidence."""
    await auth_client.post("/settings/ui-version", data={"ui_version": "masthead"})

    # Same rubric (Health), different tabs → same number, every time.
    for path in ("/weight", "/garmin", "/reports"):
        r = await auth_client.get(path, headers={"Accept": "text/html"})
        assert r.status_code == 200
        assert "Раздел 01 ·" in r.text

    # Different rubrics → their own stable number.
    r = await auth_client.get("/genetics", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Раздел 02 · Маркеры" in r.text

    r = await auth_client.get("/supplements", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Раздел 03 · Образ жизни" in r.text


async def test_settings_card_and_banner_present(auth_client):
    """The interface toggle card renders, and the saved banner shows after a switch."""
    r = await auth_client.get("/settings", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'action="/settings/ui-version"' in r.text
    assert 'name="ui_version" value="masthead"' in r.text

    r = await auth_client.get("/settings?saved=ui_version", headers={"Accept": "text/html"})
    assert r.status_code == 200
    # RU is the seeded test language.
    assert "Интерфейс переключён." in r.text


async def test_consistent_layout_max_width(auth_client):
    """Timeline, Settings, and Weight pages must have the same max-w-6xl wrapper class."""
    for path in ("/weight", "/timeline", "/settings"):
        r = await auth_client.get(path, headers={"Accept": "text/html"})
        assert r.status_code == 200
        assert "max-w-6xl" in r.text
        assert "max-w-4xl" not in r.text



