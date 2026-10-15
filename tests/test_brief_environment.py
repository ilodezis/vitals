"""Last night's bedroom air in the morning brief, and the nights × sleep tool.

The brief's air line is code, not prose, and it has to stay quiet in exactly the
cases where speaking would mislead: the module off, a station that sent nothing,
and a night it only half saw — a partial night must never read as a clean one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from fixtures.environment import flat_rows, insert_samples
from vitals.models import GarminDaily
from vitals.services import environment_context, garmin_service, modules_service
from vitals.services.proactive import brief, compose
from vitals.utils.timeutils import local_naive_to_utc

DAY = date(2026, 9, 20)

GARMIN_RAW = {
    "summary": {"restingHeartRate": 52, "bodyBatteryHighestValue": 84},
    "sleep": {"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}},
    "hrv": {"hrvSummary": {"lastNightAvg": 61}},
}


class FakeLLM:
    digest_model = "fake/digest"
    brief_model = "fake/brief"

    def __init__(self):
        self.calls: list[dict] = []

    async def complete_text(self, prompt, *, model=None, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
        return "Ночь душная, HRV ниже нормы — совпадение стоит заметить."


def _night_end(day: date) -> datetime:
    return local_naive_to_utc(datetime(day.year, day.month, day.day, 12))


async def _night(db_session, day: date, *, co2: int, temp: float = 19.0, hours: float = 12):
    """``hours`` of readings a minute apart, ending at the window's noon."""
    await insert_samples(
        db_session,
        flat_rows(_night_end(day), minutes=hours * 60, co2=co2, temp=temp, interval_s=60,
                  boot_id=f"b{day.day:02d}"),
    )


async def _usual_fortnight(db_session, *, co2: int = 700, temp: float = 19.0):
    for back in range(1, 6):
        await _night(db_session, DAY - timedelta(days=back), co2=co2, temp=temp)


async def _set_environment(db_session, enabled: bool):
    await modules_service.set_module_enabled(db_session, key="environment", enabled=enabled)
    await db_session.commit()


# ── The header line (pure) ────────────────────────────────────────────────────
THRESHOLDS = {"co2_warn": 1000, "co2_bad": 1400, "temp_sleep_min": 17, "temp_sleep_max": 20}


def _env(*, median=700, above_warn=0.0, temp_mean=19.0, baseline=None):
    return {
        "co2": {"median": median, "minutes_above_warn": above_warn},
        "temperature": {"mean": temp_mean},
        "thresholds": THRESHOLDS,
        "baseline": baseline,
    }


def test_a_stuffy_night_reads_against_his_own_nights():
    block = compose.environment_block(
        _env(median=1180, above_warn=190, baseline={"co2_median": 850})
    )
    assert block.kind == compose.KIND_ENVIRONMENT
    assert block.text == "Спальня ночью: CO₂ выше 1000 — 3 ч 10 мин, медиана 1180 (обычно 850) · 19 °C"


def test_a_median_well_above_his_norm_is_a_line_even_under_the_warn_line():
    block = compose.environment_block(_env(median=900, baseline={"co2_median": 650}))
    assert block.text == "Спальня ночью: CO₂ медиана 900 (обычно 650) · 19 °C"


def test_a_warm_room_is_named_against_his_sleeping_range():
    block = compose.environment_block(_env(temp_mean=23.5))
    assert block.text == "Спальня ночью: CO₂ медиана 700 · 23,5 °C — выше твоих 17–20"


def test_an_ordinary_night_still_prints_its_plain_numbers():
    night = _env(median=720, temp_mean=19.4, baseline={"co2_median": 700})
    night["humidity"] = {"mean": 46.6}
    block = compose.environment_block(night)
    assert block.text == "Спальня ночью: CO₂ медиана 720 · 19,4 °C · влажность 47%"


def test_no_night_prints_nothing():
    assert compose.environment_block(None) is None
    assert compose.environment_block({}) is None


def test_the_line_sits_between_recovery_and_weight():
    ctx = {
        "garmin": {"sleep_score": 80},
        "environment": _env(temp_mean=23.5),
        "weight": {"latest_kg": 88.0},
    }
    kinds = [b.kind for b in sorted(compose.header_blocks(ctx), key=lambda b: b.priority)]
    assert kinds == [compose.KIND_GARMIN, compose.KIND_ENVIRONMENT, compose.KIND_WEIGHT]


# ── The brief end to end ──────────────────────────────────────────────────────
@pytest.mark.usefixtures("all_modules_on")
async def test_a_stuffy_night_is_in_the_header_and_in_the_models_context(db_session):
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()
    await _usual_fortnight(db_session)
    await _night(db_session, DAY, co2=1200)

    llm = FakeLLM()
    row = await brief.generate_brief(db_session, llm, on_date=DAY)

    assert "Спальня ночью: CO₂ выше 1000 — 11 ч 59 мин, медиана 1200 (обычно 700)" in row.content
    env = row.context_json["environment"]
    assert env["coverage_pct"] >= environment_context.COVERAGE_ADEQUATE_PCT
    assert env["baseline"]["co2_median"] == 700 and env["baseline"]["nights"] == 5
    assert '"environment"' in llm.calls[0]["prompt"]
    # The model is told it may relate the night to sleep, not blame it.
    assert "выдуманная причина" in llm.calls[0]["system"]


@pytest.mark.usefixtures("all_modules_on")
async def test_no_line_when_the_module_is_off(db_session):
    await _usual_fortnight(db_session)
    await _night(db_session, DAY, co2=1200)
    await _set_environment(db_session, False)

    ctx = await brief.build_context(db_session, on_date=DAY)

    assert ctx["environment"] is None
    assert not any(b.kind == compose.KIND_ENVIRONMENT for b in compose.header_blocks(ctx))


@pytest.mark.usefixtures("all_modules_on")
async def test_no_line_without_station_data(db_session):
    ctx = await brief.build_context(db_session, on_date=DAY)
    assert ctx["environment"] is None


@pytest.mark.usefixtures("all_modules_on")
async def test_no_line_when_the_station_saw_only_part_of_the_night(db_session):
    await _usual_fortnight(db_session)
    await _night(db_session, DAY, co2=1500, hours=5)  # ~40% of the window

    ctx = await brief.build_context(db_session, on_date=DAY)

    assert ctx["environment"] is None
    assert not any(b.kind == compose.KIND_ENVIRONMENT for b in compose.header_blocks(ctx))


@pytest.mark.usefixtures("all_modules_on")
async def test_no_norm_until_there_are_enough_covered_nights(db_session):
    await _night(db_session, DAY - timedelta(days=1), co2=700)
    await _night(db_session, DAY - timedelta(days=2), co2=700, hours=4)  # not a norm-maker
    await _night(db_session, DAY, co2=1200)

    night = await environment_context.brief_night(db_session, DAY)

    assert "baseline" not in night
    block = compose.environment_block(night)
    assert block.text == "Спальня ночью: CO₂ выше 1000 — 11 ч 59 мин, медиана 1200 · 19 °C · влажность 45%"


def test_the_doctor_report_has_no_climate_section():
    from vitals.services import share_service

    assert "environment" not in share_service._BUILDERS


# ── MCP: nights × sleep ───────────────────────────────────────────────────────
async def test_nights_sit_beside_that_nights_sleep(db_session):
    await _night(db_session, DAY, co2=1200, temp=21.0)
    await _night(db_session, DAY - timedelta(days=1), co2=700)
    db_session.add(GarminDaily(
        date=DAY, domain="garmin", source="garmin_api",
        sleep_score=71, sleep_seconds=25200, deep_sleep_seconds=3600, hrv_avg=48.0,
        resting_hr=55, awake_count=3,
    ))
    db_session.add(GarminDaily(  # sleep with no air: still a row, air side null
        date=DAY - timedelta(days=2), domain="garmin", source="garmin_api", sleep_score=85,
    ))
    await db_session.commit()

    out = await environment_context.nights_with_sleep(
        db_session, start=DAY - timedelta(days=2), end=DAY
    )

    cols = out["columns"]
    assert cols[0] == "date" and {"co2_median", "coverage_pct", "sleep_score", "hrv"} <= set(cols)
    assert [r[0] for r in out["rows"]] == [
        (DAY - timedelta(days=2)).isoformat(), (DAY - timedelta(days=1)).isoformat(), DAY.isoformat(),
    ]
    last = dict(zip(cols, out["rows"][-1]))
    assert last["co2_median"] == 1200 and last["temp_max"] == 21.0
    assert last["sleep_score"] == 71 and last["sleep_min"] == 420 and last["deep_min"] == 60
    assert last["hrv"] == 48.0 and last["awake_count"] == 3
    first = dict(zip(cols, out["rows"][0]))
    assert first["co2_median"] is None and first["sleep_score"] == 85
    middle = dict(zip(cols, out["rows"][1]))
    assert middle["sleep_score"] is None and middle["co2_median"] == 700
    assert "truncated" not in out and out["thresholds"]["co2_warn"] == 1000


async def test_a_long_window_is_cut_and_says_so(db_session):
    out = await environment_context.nights_with_sleep(
        db_session, start=DAY - timedelta(days=60), end=DAY
    )
    assert out["truncated"] is True and "hint" in out
    span = date.fromisoformat(out["window"]["end"]) - date.fromisoformat(out["window"]["start"])
    assert span.days + 1 == environment_context.SLEEP_NIGHTS_MAX_DAYS


async def test_the_tool_is_compact_and_reads_through_the_service(session_factory, monkeypatch):
    import json

    mcp_router = pytest.importorskip("web.routers.mcp")
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: session_factory)
    await mcp_router.set_module("environment", True)
    async with session_factory() as session:
        for back in range(14):
            await _night(session, DAY - timedelta(days=back), co2=800)

    out = await mcp_router.get_environment_vs_sleep(
        start_date=(DAY - timedelta(days=13)).isoformat(), end_date=DAY.isoformat()
    )

    assert len(out["rows"]) == 14
    # Columnar: a fortnight costs about one row of names, not fourteen.
    assert len(json.dumps(out)) < 4000
    with pytest.raises(ValueError, match="start_date"):
        await mcp_router.get_environment_vs_sleep(start_date="nope")
