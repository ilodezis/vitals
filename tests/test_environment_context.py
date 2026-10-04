"""What the environment domain hands to the surfaces that read the whole lake: the
MCP tools, the AI digest and the exports.

The storage layer's own reads (``queries.series`` / ``night_summary``, ``live.get_live``)
are tested with it; here they are replaced by fakes returning its real result types,
so these tests pin the *shaping* — local times, pruned nulls, caps and honest
truncation — and keep working whichever way those reads are implemented. What is read
straight from the tables (which nights have data, the hourly rows, alert peaks) runs
against the real schema.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from fixtures.environment import insert_samples, night_rows, sample_row
from vitals.models import SystemAlert
from vitals.models.environment import EnvironmentHourly
from vitals.services import environment_context as ctx
from vitals.services.environment import live as env_live
from vitals.services.environment import queries
from vitals.services.environment.types import (
    Co2Stats,
    LiveNow,
    LiveState,
    LiveStation,
    NightSummary,
    Point,
    RangeStats,
    Window,
)
from vitals.utils.timeutils import local_naive_to_utc

UTC = timezone.utc


def local(d: date, hour: int = 0, minute: int = 0) -> datetime:
    """An aware UTC instant for a local wall-clock time (the suite runs in Chisinau)."""
    return local_naive_to_utc(datetime(d.year, d.month, d.day, hour, minute))


def night(d: date, *, samples: int = 2000, co2_max: float = 1620.0, coverage: float = 93.44) -> NightSummary:
    return NightSummary(
        date=d,
        window=Window(start=local(d), end=local(d, 12)),
        samples=samples,
        coverage_pct=coverage,
        co2=Co2Stats(median=812.4, p90=1180.0, max=co2_max, minutes_above_warn=95.0, minutes_above_bad=22.46),
        temperature=RangeStats(min=19.21, mean=20.14, max=21.0),
        humidity=RangeStats(min=44.0, mean=51.5, max=58.04),
    )


@pytest.fixture
def fake_night_summary(monkeypatch):
    """``night_summary`` for chosen dates; every other date is an empty window."""
    summaries: dict[date, NightSummary] = {}
    asked: list[date] = []

    async def fake(session, on_date, *, station_id="bedroom"):
        asked.append(on_date)
        return summaries.get(
            on_date,
            NightSummary(date=on_date, window=Window(start=local(on_date), end=local(on_date, 12))),
        )

    monkeypatch.setattr(queries, "night_summary", fake)
    fake.summaries, fake.asked = summaries, asked
    return fake


# ── shaping helpers ──────────────────────────────────────────────────────────


def test_prune_drops_nulls_and_empty_groups_but_keeps_zero():
    raw = {"a": None, "b": 0, "c": {"x": None}, "d": {"y": 1, "z": None}, "e": [{"k": None, "v": 2}], "f": ""}

    assert ctx.prune(raw) == {"b": 0, "d": {"y": 1}, "e": [{"v": 2}], "f": ""}


def test_a_night_is_shaped_in_local_time_with_rounded_numbers():
    shaped = ctx.night_dict(night(date(2026, 9, 30)))

    assert shaped == {
        "date": "2026-09-30",
        "window": {"start": "2026-09-30T00:00", "end": "2026-09-30T12:00"},
        "samples": 2000,
        "coverage_pct": 93.4,
        "co2": {"median": 812, "p90": 1180, "max": 1620, "minutes_above_warn": 95.0, "minutes_above_bad": 22.5},
        "temperature": {"min": 19.2, "mean": 20.1, "max": 21.0},
        "humidity": {"min": 44.0, "mean": 51.5, "max": 58.0},
    }


# ── the live view ────────────────────────────────────────────────────────────


async def test_live_view_before_the_station_ever_reported(db_session, monkeypatch):
    async def never(session, redis=None, *, now=None):
        return None

    monkeypatch.setattr(env_live, "get_live", never)

    view = await ctx.live_view(db_session)

    assert view["station"] == {"status": "never"}
    assert view["now"] == {"co2_zone": "none"}
    assert view["thresholds"]["co2_warn"] == 1000 and view["thresholds"]["co2_bad"] == 1400
    assert view["timezone"] == "Europe/Chisinau"


async def test_live_view_carries_the_reading_zone_trend_and_a_local_last_seen(db_session, monkeypatch):
    state = LiveState(
        station=LiveStation(
            status="online", last_seen_at=datetime(2026, 10, 5, 11, 30, 12, tzinfo=UTC), age_s=4, rssi=-61, fw="env-1.1.0"
        ),
        now=LiveNow(co2_ppm=1520, temperature_c=21.4, humidity_pct=41.2, co2_zone="bad", co2_trend_ppm_per_h=240.0),
    )

    async def fake(session, redis=None, *, now=None):
        return state

    monkeypatch.setattr(env_live, "get_live", fake)

    view = await ctx.live_view(db_session)

    assert view["station"] == {
        "status": "online", "last_seen_at": "2026-10-05T14:30:12", "age_s": 4, "rssi": -61, "fw": "env-1.1.0",
    }
    assert view["now"] == {
        "co2_ppm": 1520, "temperature_c": 21.4, "humidity_pct": 41.2, "co2_zone": "bad", "co2_trend_ppm_per_h": 240.0,
    }


async def test_a_redis_outage_does_not_blind_the_live_view(db_session, monkeypatch):
    """The cache is an accelerator: with it down the tool reads the database instead
    of failing the whole call."""
    calls = []

    async def fake(session, redis=None, *, now=None):
        calls.append(redis)
        if redis is not None:
            raise ConnectionError("redis is down")
        return LiveState(station=LiveStation(status="stale"))

    monkeypatch.setattr(env_live, "get_live", fake)

    view = await ctx.live_view(db_session, redis=object())

    assert view["station"]["status"] == "stale"
    assert len(calls) == 2 and calls[1] is None


# ── the history view ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_series(monkeypatch):
    """Record what ``series`` is asked and answer with chosen points."""
    seen: dict = {"points": [], "calls": []}

    async def series(session, start, end, *, resolution, station_id="bedroom"):
        seen["calls"].append((start, end, resolution))
        return list(seen["points"])

    async def coverage(session, start, end, *, station_id="bedroom"):
        return 87.26

    monkeypatch.setattr(queries, "series", series)
    monkeypatch.setattr(queries, "coverage_pct", coverage)
    return seen


def hour_point(day: date, hour: int, co2: float, **kw) -> Point:
    return Point(ts=local(day, hour), co2_ppm=co2, co2_max=co2 + 40, co2_min=co2 - 30,
                 temperature_c=21.37, humidity_pct=44.04, **kw)


async def test_hourly_history_is_columnar_local_and_rounded(db_session, fake_series):
    fake_series["points"] = [hour_point(date(2026, 10, 4), 23, 612.4), hour_point(date(2026, 10, 5), 0, 655.0)]

    out = await ctx.history_view(db_session, start=date(2026, 10, 4), end=date(2026, 10, 5), granularity="hour", limit=800)

    assert out["granularity"] == "hour"
    assert out["columns"] == ["ts", "co2_ppm", "co2_max", "co2_min", "temperature_c", "humidity_pct"]
    assert out["rows"] == [
        ["2026-10-04T23:00", 612, 652, 582, 21.4, 44.0],
        ["2026-10-05T00:00", 655, 695, 625, 21.4, 44.0],
    ]
    assert out["count"] == 2 and out["truncated"] is False
    assert out["window"] == {"start": "2026-10-04", "end": "2026-10-05"}
    assert out["coverage_pct"] == 87.3
    assert out["timezone"] == "Europe/Chisinau"
    assert out["thresholds"]["co2_warn"] == 1000


async def test_history_asks_for_whole_local_days_in_utc(db_session, fake_series):
    await ctx.history_view(db_session, start=date(2026, 10, 1), end=date(2026, 10, 2), granularity="hour", limit=800)

    start, end, resolution = fake_series["calls"][0]
    assert start == datetime(2026, 9, 30, 21, 0, tzinfo=UTC)   # 1 Oct 00:00 in Chisinau
    assert end == datetime(2026, 10, 2, 21, 0, tzinfo=UTC)     # the end date is inclusive
    assert resolution == "hour"


async def test_minute_history_drops_the_columns_hours_only_carry(db_session, fake_series):
    fake_series["points"] = [Point(ts=local(date(2026, 10, 5), 3, 7), co2_ppm=900.0, temperature_c=20.0, humidity_pct=50.0)]

    out = await ctx.history_view(db_session, start=date(2026, 10, 5), end=date(2026, 10, 5), granularity="minute", limit=800)

    assert out["columns"] == ["ts", "co2_ppm", "temperature_c", "humidity_pct"]
    assert out["rows"] == [["2026-10-05T03:07", 900, 20.0, 50.0]]


async def test_a_light_column_appears_only_once_a_sensor_reports_it(db_session, fake_series):
    fake_series["points"] = [hour_point(date(2026, 10, 5), 1, 700.0, lux=3.456)]

    out = await ctx.history_view(db_session, start=date(2026, 10, 5), end=date(2026, 10, 5), granularity="hour", limit=800)

    assert "lux" in out["columns"]
    assert out["rows"][0][out["columns"].index("lux")] == 3.5


async def test_hour_history_longer_than_a_month_is_cut_and_says_so(db_session, fake_series):
    out = await ctx.history_view(db_session, start=date(2026, 8, 1), end=date(2026, 10, 5), granularity="hour", limit=800)

    assert out["window"] == {"start": "2026-08-01", "end": "2026-08-31"}  # the first 31 days
    assert out["truncated"] is True
    assert "start_date" in out["hint"] and "31" in out["hint"]
    start, end, _ = fake_series["calls"][0]
    assert end == local(date(2026, 9, 1))


async def test_minute_history_is_capped_at_two_days(db_session, fake_series):
    out = await ctx.history_view(db_session, start=date(2026, 10, 1), end=date(2026, 10, 5), granularity="minute", limit=3000)

    assert out["window"] == {"start": "2026-10-01", "end": "2026-10-02"}
    assert out["truncated"] is True and "2" in out["hint"]


async def test_a_point_limit_truncates_to_the_first_points_and_reports_the_rest(db_session, fake_series):
    fake_series["points"] = [hour_point(date(2026, 10, 5), h, 600.0 + h) for h in range(10)]

    out = await ctx.history_view(db_session, start=date(2026, 10, 5), end=date(2026, 10, 5), granularity="hour", limit=3)

    assert out["count"] == 3 and out["available"] == 10 and out["truncated"] is True
    assert [r[0] for r in out["rows"]] == ["2026-10-05T00:00", "2026-10-05T01:00", "2026-10-05T02:00"]
    assert "limit" in out["hint"]


@pytest.mark.parametrize("limit,expected", [(0, 1), (-5, 1), (10_000, 3000)])
async def test_the_point_limit_is_clamped(db_session, fake_series, limit, expected):
    fake_series["points"] = [hour_point(date(2026, 10, 5), h % 24, 600.0) for h in range(5000)]

    out = await ctx.history_view(db_session, start=date(2026, 10, 1), end=date(2026, 10, 31), granularity="hour", limit=limit)

    assert out["count"] == expected


async def test_default_window_is_the_last_week_for_hours_and_one_day_for_minutes(db_session, fake_series, monkeypatch):
    monkeypatch.setattr(ctx.timeutils, "today_local", lambda: date(2026, 10, 5))

    hours = await ctx.history_view(db_session, start=None, end=None, granularity="hour", limit=800)
    minutes = await ctx.history_view(db_session, start=None, end=None, granularity="minute", limit=800)

    assert hours["window"] == {"start": "2026-09-29", "end": "2026-10-05"}
    assert minutes["window"] == {"start": "2026-10-05", "end": "2026-10-05"}


@pytest.mark.parametrize("granularity", ["raw", "sample", "night", "day", ""])
async def test_other_granularities_are_refused_with_the_valid_ones(db_session, fake_series, granularity):
    out = await ctx.history_view(db_session, start=None, end=None, granularity=granularity, limit=800)

    assert "hour" in out["error"] and "minute" in out["error"]
    assert fake_series["calls"] == []


async def test_a_reversed_window_is_refused(db_session, fake_series):
    out = await ctx.history_view(db_session, start=date(2026, 10, 5), end=date(2026, 10, 1), granularity="hour", limit=800)

    assert "start_date" in out["error"]


# ── the night view ───────────────────────────────────────────────────────────


async def test_night_view_adds_the_owners_sleeping_lines(db_session, fake_night_summary):
    fake_night_summary.summaries[date(2026, 9, 30)] = night(date(2026, 9, 30))

    out = await ctx.night_view(db_session, date(2026, 9, 30))

    assert out["co2"]["max"] == 1620 and out["window"]["start"] == "2026-09-30T00:00"
    assert out["thresholds"]["temp_sleep_min"] == 17 and out["thresholds"]["temp_sleep_max"] == 20
    assert out["timezone"] == "Europe/Chisinau"
    assert "note" not in out


async def test_a_night_without_readings_says_so_instead_of_returning_zeros(db_session, fake_night_summary):
    out = await ctx.night_view(db_session, date(2026, 9, 30))

    assert out["samples"] == 0 and "no station readings" in out["note"].lower()
    assert "co2" not in out
    assert out["window"] == {"start": "2026-09-30T00:00", "end": "2026-09-30T12:00"}


# ── nights across a range ────────────────────────────────────────────────────


async def test_nights_lists_only_dates_that_have_station_data(db_session, fake_night_summary):
    for d in (date(2026, 9, 28), date(2026, 9, 30)):
        fake_night_summary.summaries[d] = night(d)
    # another seed is another boot id, so the two nights do not collide on (boot, seq)
    await insert_samples(db_session, night_rows(date(2026, 9, 28), "ok", interval_s=600, seed=1)
                         + night_rows(date(2026, 9, 30), "stuffy", interval_s=600, seed=2))

    found, truncated = await ctx.nights(db_session, date(2026, 9, 1), date(2026, 10, 5))

    assert [n.date for n in found] == [date(2026, 9, 28), date(2026, 9, 30)]
    assert truncated is False
    assert fake_night_summary.asked == [date(2026, 9, 28), date(2026, 9, 30)]  # no query for the empty days


async def test_nights_skips_a_date_whose_window_holds_no_samples(db_session, fake_night_summary):
    """An afternoon-only day has samples but no night: the summary comes back empty."""
    await insert_samples(db_session, [sample_row(local(date(2026, 9, 30), 15), co2=700)])

    found, _ = await ctx.nights(db_session, date(2026, 9, 1), date(2026, 10, 5))

    assert found == []


async def test_nights_keeps_the_newest_when_there_are_more_than_the_limit(db_session, fake_night_summary):
    days = [date(2026, 9, 20) + timedelta(days=i) for i in range(5)]
    for d in days:
        fake_night_summary.summaries[d] = night(d)
    await insert_samples(db_session, [sample_row(local(d, 2), co2=700, seq=i + 1) for i, d in enumerate(days)])

    found, truncated = await ctx.nights(db_session, date(2026, 9, 1), date(2026, 10, 5), limit=3)

    assert [n.date for n in found] == days[-3:] and truncated is True


async def test_nights_without_a_lower_bound_reads_the_whole_history(db_session, fake_night_summary):
    fake_night_summary.summaries[date(2025, 1, 2)] = night(date(2025, 1, 2))
    await insert_samples(db_session, [sample_row(local(date(2025, 1, 2), 2), co2=700)])

    found, _ = await ctx.nights(db_session, None, None, limit=None)

    assert [n.date for n in found] == [date(2025, 1, 2)]


# ── hours, as they go into an export ─────────────────────────────────────────


def hourly_row(d: date, hour: int, **kw) -> EnvironmentHourly:
    base = dict(
        station_id="bedroom", hour_start=local(d, hour), date=d, domain="environment", source="esphome",
        sample_count=360, coverage_pct=100.0, co2_mean=700.4, co2_min=650, co2_max=780, co2_p90=760.0,
        temp_mean=21.46, temp_min=21.0, temp_max=22.0, rh_mean=44.04, rh_min=43.0, rh_max=46.0,
    )
    base.update(kw)
    return EnvironmentHourly(**base)


async def test_hours_come_out_one_entry_per_day_with_parallel_arrays(db_session):
    d1, d2 = date(2026, 10, 3), date(2026, 10, 4)
    db_session.add_all([
        hourly_row(d1, 23, co2_mean=900.0, co2_max=990, coverage_pct=50.0),
        hourly_row(d2, 0),
        hourly_row(d2, 1, co2_mean=None, co2_max=None, temp_mean=None),
    ])
    await db_session.commit()

    days = await ctx.hours_by_day(db_session, None, None)

    assert days == [
        {"date": "2026-10-03", "hours": ["23"], "coverage_pct": [50], "co2_mean": [900], "co2_max": [990],
         "temperature_mean": [21.5], "humidity_mean": [44.0]},
        {"date": "2026-10-04", "hours": ["00", "01"], "coverage_pct": [100, 100], "co2_mean": [700, None],
         "co2_max": [780, None], "temperature_mean": [21.5, None], "humidity_mean": [44.0, 44.0]},
    ]


async def test_hours_respect_the_lower_bound(db_session):
    db_session.add_all([hourly_row(date(2026, 9, 1), 3), hourly_row(date(2026, 10, 1), 3)])
    await db_session.commit()

    days = await ctx.hours_by_day(db_session, date(2026, 9, 15), None)

    assert [d["date"] for d in days] == ["2026-10-01"]


async def test_a_day_with_the_clocks_going_back_keeps_both_repeated_hours(db_session):
    """25 October 2026: Chisinau goes from 03:00 back to 02:00 at 00:00 UTC, so the
    local hour "02" happens twice. The labels repeat; the arrays still line up."""
    d = date(2026, 10, 25)
    first = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)  # 02:00 EEST
    db_session.add_all([
        hourly_row(d, 0, hour_start=first, co2_mean=600.0),
        hourly_row(d, 0, hour_start=first + timedelta(hours=1), co2_mean=640.0),  # 02:00 EET
    ])
    await db_session.commit()

    day = (await ctx.hours_by_day(db_session, d, d))[0]

    assert day["hours"] == ["02", "02"] and day["co2_mean"] == [600, 640]


# ── alerts that fired ────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 5, 12, 0)  # naive local, like every other "now" in the app


def alert(key, started, ended=None, *, severity="warn", domain="environment", message="m"):
    return SystemAlert(domain=domain, severity=severity, message=message, alert_key=key,
                       entity_ref=started.isoformat(), created_at=started, resolved_at=ended)


async def test_an_alert_episode_comes_with_its_peak_read_off_the_samples(db_session):
    started, ended = datetime(2026, 10, 5, 3, 10), datetime(2026, 10, 5, 3, 40)
    db_session.add(alert("env_co2_bad", started, ended, message="Душно: CO₂ 1520 ppm"))
    await db_session.commit()
    await insert_samples(db_session, [
        sample_row(local(date(2026, 10, 5), 3, 5), co2=1380, seq=1),   # before it fired
        sample_row(local(date(2026, 10, 5), 3, 20), co2=1620, seq=2),  # the peak
        sample_row(local(date(2026, 10, 5), 3, 30), co2=1450, seq=3),
        sample_row(local(date(2026, 10, 5), 3, 50), co2=2000, seq=4),  # after it ended: not part of it
    ])

    out = await ctx.alerts_view(db_session, hours=24, now=NOW)

    assert out["alerts"] == [{
        "key": "env_co2_bad", "severity": "warn", "message": "Душно: CO₂ 1520 ppm",
        "started_at": "2026-10-05T03:10:00", "ended_at": "2026-10-05T03:40:00", "ongoing": False, "minutes": 30,
        "peak": {"metric": "co2_ppm", "value": 1620, "at": "2026-10-05T03:20:00"},
    }]
    assert out["hours"] == 24


async def test_an_ongoing_alert_peaks_up_to_now(db_session):
    db_session.add(alert("env_co2_bad", datetime(2026, 10, 5, 11, 0)))
    await db_session.commit()
    await insert_samples(db_session, [
        sample_row(local(date(2026, 10, 5), 11, 30), co2=1500, seq=1),
        sample_row(local(date(2026, 10, 5), 11, 50), co2=1700, seq=2),
    ])

    (row,) = (await ctx.alerts_view(db_session, hours=24, now=NOW))["alerts"]

    assert row["ongoing"] is True and "ended_at" not in row
    assert row["minutes"] == 60 and row["peak"]["value"] == 1700


@pytest.mark.parametrize("key,column,rows,expected", [
    ("env_temp_high", "temperature_c", [27.5, 29.1, 28.0], 29.1),
    ("env_temp_low", "temperature_c", [16.0, 14.2, 15.0], 14.2),
    ("env_rh_high", "humidity_pct", [71.0, 78.5, 74.0], 78.5),
    ("env_rh_low", "humidity_pct", [28.0, 22.5, 25.0], 22.5),
])
async def test_each_rule_peaks_in_its_own_direction(db_session, key, column, rows, expected):
    db_session.add(alert(key, datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 10, 0)))
    await db_session.commit()
    await insert_samples(db_session, [
        sample_row(local(date(2026, 10, 5), 9, 10 * (i + 1)), seq=i + 1, **{"temp" if column == "temperature_c" else "rh": v})
        for i, v in enumerate(rows)
    ])

    (row,) = (await ctx.alerts_view(db_session, hours=24, now=NOW))["alerts"]

    assert row["peak"]["value"] == expected
    assert row["peak"]["metric"] == column


async def test_a_silent_station_has_a_length_and_no_peak(db_session):
    db_session.add(alert("env_station_silent", datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 8, 47), severity="warn"))
    await db_session.commit()

    (row,) = (await ctx.alerts_view(db_session, hours=24, now=NOW))["alerts"]

    assert row["minutes"] == 47 and "peak" not in row


async def test_only_environment_alerts_inside_the_window_are_listed_newest_first(db_session):
    db_session.add_all([
        alert("env_co2_bad", datetime(2026, 10, 3, 3, 0), datetime(2026, 10, 3, 3, 30)),    # two days ago
        alert("env_co2_warn", datetime(2026, 10, 5, 6, 0), datetime(2026, 10, 5, 6, 20), severity="info"),
        alert("env_temp_high", datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 5, 10, 30)),
        alert("garmin_sync_stale", datetime(2026, 10, 5, 9, 0), domain="garmin"),
        # started long ago but still open: it belongs to every window until it ends
        alert("env_rh_low", datetime(2026, 10, 1, 9, 0)),
    ])
    await db_session.commit()

    out = await ctx.alerts_view(db_session, hours=24, now=NOW)

    assert [a["key"] for a in out["alerts"]] == ["env_temp_high", "env_co2_warn", "env_rh_low"]
    assert out["active"] == 1


async def test_the_alert_window_is_clamped_to_a_week(db_session):
    db_session.add(alert("env_co2_bad", datetime(2026, 9, 20, 3, 0), datetime(2026, 9, 20, 3, 30)))
    await db_session.commit()

    assert (await ctx.alerts_view(db_session, hours=100_000, now=NOW))["hours"] == 168
    assert (await ctx.alerts_view(db_session, hours=0, now=NOW))["hours"] == 1


async def test_no_alerts_is_an_empty_list_not_an_error(db_session):
    out = await ctx.alerts_view(db_session, hours=24, now=NOW)

    assert out["alerts"] == [] and out["active"] == 0
