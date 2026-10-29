"""MCP timeline tools — get_timeline / log_event, plus the module-disabled
no-op path for the write tool."""
from __future__ import annotations

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")

from vitals.models.app_settings import AppSetting  # noqa: E402
from vitals.services.modules_service import MODULE_REGISTRY, SETTINGS_KEY  # noqa: E402


async def _enable_timeline(db_session):
    db_session.add(AppSetting(key=SETTINGS_KEY, value={k: True for k in MODULE_REGISTRY}))
    await db_session.commit()


async def test_log_event_and_get_timeline(db_session, session_factory, monkeypatch):
    await _enable_timeline(db_session)
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    res = await mcp_router.log_event(
        title="Поездка в Грузию",
        on_date="2026-06-01",
        end_date="2026-06-10",
        kind="travel",
        domain="timeline",
    )
    assert "error" not in res
    assert res["title"] == "Поездка в Грузию"
    assert res["kind"] == "travel"

    events = await mcp_router.get_timeline()
    assert any(e["title"] == "Поездка в Грузию" for e in events)

    by_domain = await mcp_router.get_timeline(domain="weight")
    # A global ("timeline") annotation is still relevant everywhere.
    assert any(e["title"] == "Поездка в Грузию" for e in by_domain)

    by_range = await mcp_router.get_timeline(start_date="2026-07-01", end_date="2026-07-31")
    assert by_range == []


async def test_log_event_noop_when_module_disabled(db_session, session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    from vitals.models.app_settings import AppSetting
    from vitals.services.modules_service import MODULE_REGISTRY, SETTINGS_KEY

    db_session.add(AppSetting(
        key=SETTINGS_KEY,
        value={k: (k not in ("timeline",)) for k in MODULE_REGISTRY},
    ))
    await db_session.commit()

    res = await mcp_router.log_event(title="Should not save", on_date="2026-06-01")
    assert res == {"error": "module 'timeline' is disabled"}


async def test_update_event_keeps_what_the_call_left_out(db_session, session_factory, monkeypatch):
    await _enable_timeline(db_session)
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)

    created = await mcp_router.log_event(
        title="Простуда",
        on_date="2026-06-01",
        end_date="2026-06-05",
        kind="illness",
        domain="timeline",
        note="температура три дня",
    )

    renamed = await mcp_router.update_event(created["id"], title="Простуда с температурой")
    assert renamed["title"] == "Простуда с температурой"
    # A rename must not cost the event its date, span, kind or note.
    assert renamed["date"] == "2026-06-01"
    assert renamed["end_date"] == "2026-06-05"
    assert renamed["kind"] == "illness"
    assert renamed["note"] == "температура три дня"

    assert await mcp_router.update_event(9999, title="x") == {"error": "Event 9999 not found"}

    assert await mcp_router.delete_record("timeline", created["id"], confirm=True) == {
        "deleted": True, "domain": "timeline", "record_id": created["id"],
    }
    assert await mcp_router.get_timeline() == []
