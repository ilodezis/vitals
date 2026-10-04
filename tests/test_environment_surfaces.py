"""Where the bedroom's air shows up beside the rest of the lake — and where it must not.

The AI report and the exports carry the nights (summaries, never curves); the data
overview counts the rows; the doctor report and the public report never see climate
at all. As in ``test_environment_context``, the storage layer's own night summary is a
fake returning its real result type: this file is about the wiring.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from fixtures.environment import insert_samples, sample_row
from vitals.models.environment import EnvironmentHourly
from vitals.services import data_portability_service, digest_service, modules_service, share_service
from vitals.services.environment import queries
from vitals.services.environment.types import Co2Stats, NightSummary, RangeStats, Window
from vitals.utils.timeutils import local_naive_to_utc

DAY = date(2026, 6, 10)


def utc(d: date, hour: int = 0) -> datetime:
    return local_naive_to_utc(datetime(d.year, d.month, d.day, hour))


def night(d: date, *, samples: int = 1500, co2_max: float = 1500.0) -> NightSummary:
    return NightSummary(
        date=d, window=Window(start=utc(d), end=utc(d, 12)), samples=samples, coverage_pct=88.0,
        co2=Co2Stats(median=800.0, p90=1100.0, max=co2_max, minutes_above_warn=60.0, minutes_above_bad=10.0),
        temperature=RangeStats(min=19.0, mean=20.0, max=21.0),
        humidity=RangeStats(min=40.0, mean=46.0, max=52.0),
    )


@pytest.fixture
def summaries(monkeypatch):
    """``night_summary`` answers for chosen dates (empty windows elsewhere); records the asks."""
    known: dict[date, NightSummary] = {}
    asked: list[date] = []

    async def fake(session, on_date, *, station_id="bedroom"):
        asked.append(on_date)
        return known.get(on_date, NightSummary(date=on_date, window=Window(start=utc(on_date), end=utc(on_date, 12))))

    monkeypatch.setattr(queries, "night_summary", fake)
    fake.known, fake.asked = known, asked
    return fake


async def seed_nights(session, days):
    """One 02:00 sample per date, so those dates exist as nights with data."""
    await insert_samples(session, [sample_row(utc(d, 2), co2=800, seq=i + 1) for i, d in enumerate(days)])


# ── the AI report's context ──────────────────────────────────────────────────


async def test_the_context_has_no_environment_block_while_the_module_is_off(db_session, summaries):
    summaries.known[date(2026, 6, 8)] = night(date(2026, 6, 8))
    await seed_nights(db_session, [date(2026, 6, 8)])

    ctx = await digest_service.assemble_context(db_session, on_date=DAY)

    assert ctx["environment"] is None
    assert ctx["coverage"]["environment"]["status"] == "disabled"
    assert summaries.asked == []  # a switched-off module is not even queried


async def test_the_context_carries_the_nights_of_both_windows_labelled(db_session, summaries, all_modules_on):
    window = digest_service.report_window(on_date=DAY, period_days=7)
    current, previous = window.period_end, window.previous_start
    before, after = window.previous_start - timedelta(days=1), DAY
    days = [before, previous, current, after]
    for d in days:
        summaries.known[d] = night(d)
    await seed_nights(db_session, days)

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)

    env = ctx["environment"]
    assert [(n["date"], n["period"]) for n in env["nights"]] == [
        (previous.isoformat(), "previous"),
        (current.isoformat(), "current"),
    ]
    first = env["nights"][1]
    assert first["co2"]["max"] == 1500 and first["coverage_pct"] == 88.0
    assert first["window"] == {"start": f"{current.isoformat()}T00:00", "end": f"{current.isoformat()}T12:00"}
    assert env["thresholds"]["co2_warn"] == 1000 and env["thresholds"]["temp_sleep_max"] == 20
    assert "curve" not in env and "series" not in env

    cov = ctx["coverage"]["environment"]
    assert cov["status"] == "available" and cov["enabled"] is True
    assert cov["current_rows"] == 1 and cov["previous_rows"] == 1 and cov["truncated"] is False
    assert cov["last_date"] == current.isoformat()


async def test_the_context_says_empty_when_the_module_is_on_but_nothing_was_measured(db_session, summaries, all_modules_on):
    ctx = await digest_service.assemble_context(db_session, on_date=DAY)

    assert ctx["environment"] is None
    assert ctx["coverage"]["environment"]["status"] == "empty"
    assert ctx["coverage"]["environment"]["enabled"] is True


async def test_the_context_flags_when_there_are_more_nights_than_it_carries(db_session, summaries, all_modules_on, monkeypatch):
    from vitals.services import environment_context

    monkeypatch.setattr(environment_context, "NIGHTS_LIMIT", 3)
    window = digest_service.report_window(on_date=DAY, period_days=7)
    days = [window.period_end - timedelta(days=i) for i in range(5)]
    for d in days:
        summaries.known[d] = night(d)
    await seed_nights(db_session, days)

    ctx = await digest_service.assemble_context(db_session, on_date=DAY, period_days=7)

    assert len(ctx["environment"]["nights"]) == 3
    assert ctx["coverage"]["environment"]["truncated"] is True
    # the newest are kept
    assert ctx["environment"]["nights"][-1]["date"] == window.period_end.isoformat()


async def test_the_daily_brief_does_not_carry_the_room_yet(db_session, summaries, all_modules_on):
    d = date(2026, 6, 9)
    summaries.known[d] = night(d)
    await seed_nights(db_session, [d])

    ctx = await digest_service.assemble_context(
        db_session, on_date=DAY, period_days=1, mode=digest_service.REPORT_MODE_BRIEF
    )

    assert ctx["environment"] is None
    assert summaries.asked == []


def test_both_report_prompts_explain_the_environment_block():
    for prompt in (digest_service.DIGEST_SYSTEM, digest_service.DIGEST_SYSTEM_EN):
        assert "environment" in prompt
        assert "coverage_pct" in prompt


# ── the exports ──────────────────────────────────────────────────────────────


async def seed_air(session, summaries, nights=(date(2026, 6, 8), date(2026, 6, 9))):
    for d in nights:
        summaries.known[d] = night(d)
    await seed_nights(session, nights)
    session.add(EnvironmentHourly(
        station_id="bedroom", hour_start=utc(nights[0], 3), date=nights[0], domain="environment", source="esphome",
        sample_count=360, coverage_pct=100.0, co2_mean=900.0, co2_max=1000, temp_mean=20.0, rh_mean=46.0,
    ))
    await session.commit()


async def test_the_llm_export_carries_nights_and_hours(db_session, summaries):
    await seed_air(db_session, summaries)

    out = await data_portability_service.export_llm(db_session)

    assert [n["date"] for n in out["environment_nights"]] == ["2026-06-08", "2026-06-09"]
    assert out["environment_nights"][0]["co2"]["max"] == 1500
    (day,) = out["environment_hours"]
    assert day["date"] == "2026-06-08" and day["hours"] == ["03"] and day["co2_mean"] == [900]


async def test_the_llm_export_leaves_out_the_raw_samples(db_session, summaries):
    await seed_air(db_session, summaries)

    out = await data_portability_service.export_llm(db_session)

    assert "environment_samples" not in out


async def test_the_export_honours_since(db_session, summaries):
    await seed_air(db_session, summaries)

    out = await data_portability_service.export_llm(db_session, since=date(2026, 6, 9))

    assert [n["date"] for n in out["environment_nights"]] == ["2026-06-09"]
    assert out["environment_hours"] == []  # the only hourly row is on the 8th


async def test_naming_the_nights_block_skips_the_hours_and_vice_versa(db_session, summaries):
    await seed_air(db_session, summaries)

    summaries.asked.clear()
    only_hours = await data_portability_service.export_llm(db_session, domains=["environment_hours"])
    assert set(only_hours) == {"profile", "environment_hours"}
    assert summaries.asked == []  # the hours need no night summaries

    only_nights = await data_portability_service.export_llm(db_session, domains=["environment_nights"])
    assert set(only_nights) == {"profile", "environment_nights"}


async def test_other_domains_do_not_pay_for_the_environment_queries(db_session, summaries):
    await seed_air(db_session, summaries)
    summaries.asked.clear()

    out = await data_portability_service.export_llm(db_session, domains=["weight_history"])

    assert set(out) == {"profile", "weight_history"}
    assert summaries.asked == []


async def test_an_unknown_domain_lists_the_environment_blocks_among_the_valid_ones(db_session, summaries):
    with pytest.raises(ValueError) as err:
        await data_portability_service.export_llm(db_session, domains=["climate"])

    message = str(err.value)
    assert "environment_nights" in message and "environment_hours" in message


# ── what must never leave the building ───────────────────────────────────────


async def test_climate_never_reaches_a_doctor_report_even_when_asked_for(db_session, summaries, all_modules_on):
    """The doctor report and the public link are built from an explicit list of
    domains. The bedroom's air is not on it, with the module on and data present, and
    naming it anyway changes nothing."""
    import json

    enabled = await modules_service.get_enabled_modules(db_session)
    summaries.known[date(2026, 6, 8)] = night(date(2026, 6, 8))
    await seed_nights(db_session, [date(2026, 6, 8)])

    assert enabled["environment"] is True
    assert "environment" not in share_service.DOMAIN_MODULE
    assert "environment" not in share_service.available_domains(enabled)
    for preset in share_service.PRESETS.values():
        assert "environment" not in preset["domains"]

    snap = await share_service.build_snapshot(
        db_session,
        domains=["environment", "weight"],
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 9),
        enabled=enabled,
    )

    assert "environment" not in snap["domains"] and "environment" not in snap["blocks"]
    flat = json.dumps(snap, ensure_ascii=False).lower()
    assert "co2" not in flat and "ppm" not in flat
