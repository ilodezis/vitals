"""The tool surface is re-sent with every message of every conversation, and every
read answers with a hundred rows — so three things have to stay true or the budget
quietly doubles again:

  * a serialized row carries data, not bookkeeping and not nulls;
  * a night's minute-by-minute stage timeline arrives on request, not by default,
    and says so when it is folded away (silence would read as "no such data");
  * a switched-off module's tools are not listed at all.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

mcp_router = pytest.importorskip("web.routers.mcp")

from vitals.models import GarminDaily, WeightLog  # noqa: E402


@pytest.fixture(autouse=True)
def _use_test_factory(session_factory, monkeypatch):
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)


def test_serialize_row_keeps_the_data_and_drops_the_bookkeeping():
    row = WeightLog(
        id=7, date=date(2026, 7, 1), weight_kg=88.4, note=None,
        domain="weight", source="manual", superseded=False,
    )
    d = mcp_router.serialize_row(row)

    # Addressable and answerable: an edit or a delete needs the id, the weight
    # question needs date/value, and provenance decides which row wins.
    assert d["id"] == 7 and d["date"] == "2026-07-01" and d["weight_kg"] == 88.4
    assert d["source"] == "manual"
    # False is data, not absence — dropping it would hide a superseded row.
    assert d["superseded"] is False
    # Nothing a tool call can act on.
    assert "note" not in d  # unset
    for key in ("domain", "created_at", "updated_at", "raw_payload_id"):
        assert key not in d


async def _one_night(db_session):
    stages = [
        {"start": "2026-06-30T23:10:00", "end": "2026-07-01T00:05:00", "stage": "light"}
    ] * 28
    db_session.add(GarminDaily(
        date=date(2026, 7, 1), domain="garmin", source="garmin",
        sleep_score=82, sleep_seconds=25200, sleep_start=datetime(2026, 6, 30, 23, 10),
        sleep_stages=stages,
        breathing_events=[{"start": "2026-07-01T02:11:00", "end": "2026-07-01T02:14:00", "value": 3}] * 6,
    ))
    await db_session.commit()
    return stages


async def test_sleep_detail_is_folded_by_default_but_announced(db_session):
    stages = await _one_night(db_session)

    folded = await mcp_router.get_garmin_metrics()
    row = folded["daily_recovery"][0]

    # The summary the question usually needs is untouched.
    assert row["sleep_score"] == 82
    # The hypnogram is replaced by a count — the model can tell "folded" from "not measured"
    assert row["sleep_stages_count"] == len(stages)
    assert row["breathing_events_count"] == 6
    assert "sleep_stages" not in row
    assert "breathing_events" not in row

    full = await mcp_router.get_garmin_metrics(sleep_detail=True)
    assert full["daily_recovery"][0]["sleep_stages"] == stages
    assert full["daily_recovery"][0]["sleep_stages_count"] == len(stages)

    # The point of the exercise: the default response is a fraction of the size.
    assert len(json.dumps(folded)) * 3 < len(json.dumps(full))


async def test_sleep_detail_is_independent_of_intraday(db_session):
    """Asking for one night's shape must not drag every curve along with it."""
    await _one_night(db_session)
    result = await mcp_router.get_garmin_metrics(sleep_detail=True)
    assert "intraday" not in result


async def test_a_night_without_stages_says_nothing_at_all(db_session):
    """No breadcrumb where there is no data — an empty column stays absent."""
    db_session.add(GarminDaily(
        date=date(2026, 7, 2), domain="garmin", source="garmin", sleep_score=70
    ))
    await db_session.commit()

    row = (await mcp_router.get_garmin_metrics())["daily_recovery"][0]
    assert "sleep_stages" not in row and "breathing_events" not in row


def test_every_mapped_tool_name_is_a_real_tool():
    """A rename must not leave a domain's tools listed for a module that is off."""
    for name in mcp_router.TOOL_MODULES:
        assert callable(getattr(mcp_router, name, None)), f"{name} is not a tool"


async def test_disabled_modules_drop_out_of_the_tool_list(db_session, monkeypatch):
    """Optional modules default to off, so the surface starts trimmed; turning one
    on brings exactly its own tools back."""
    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "get_weight_logs" in listed  # core, never hidden
    assert "log_hrt_dose" not in listed and "get_hrt_cycles" not in listed

    from vitals.services import modules_service

    await modules_service.set_module_enabled(db_session, key="hrt", enabled=True)
    await db_session.commit()

    listed = {t.name for t in await mcp_router.mcp.list_tools()}
    assert "log_hrt_dose" in listed and "get_hrt_cycles" in listed
    assert "get_signals" not in listed  # still off
