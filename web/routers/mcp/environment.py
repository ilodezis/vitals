"""The bedroom air station."""
from __future__ import annotations

from typing import Optional


from vitals.utils.timeutils import today_local
from web.routers.mcp._core import (
    READ, _parse_date, gated, get_redis_client, get_session_factory, dispatch, tool,
)

# ── Environment tools (the bedroom's air — optional module) ───────────────────
# Reads only, from a CO2 / temperature / humidity station that measures around the
# clock. Gated like the optional domains' writes: with the module off they refuse
# and are not listed. The shaping (local times, rounding, honest truncation) lives in
# ``environment_context`` so the weekly report and the exports read the same numbers.
@gated("environment")
async def get_environment_live() -> dict:
    """Returns what the bedroom station reads right now: CO2 (ppm), temperature,
    humidity, the CO2 zone (good/ok/warn/bad), the CO2 trend in ppm per hour, and
    whether the station is online, stale, offline or has never reported — plus the
    owner's thresholds. Times are local. Read-only."""
    from vitals.services import environment_context

    try:
        redis = get_redis_client()
    except Exception:
        redis = None  # the cache only accelerates; the database still answers
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.live_view(session, redis)


@gated("environment")
async def get_environment_series(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = "hour",
    limit: int = 800,
) -> dict:
    """Retrieves the bedroom's air — CO2 (ppm), temperature (°C), humidity (%) —
    over whole local days (YYYY-MM-DD, both ends inclusive), as ``columns`` plus
    ``rows``. ``granularity`` is ``hour`` (up to 31 days; default the last 7; each
    hour also carries its CO2 min and max) or ``minute`` (up to 2 days; default
    today). A longer window or more than ``limit`` points (default 800, max 3000)
    is cut to its FIRST part and flagged with ``truncated`` and a ``hint`` — narrow
    the dates to see the rest. Raw 10-second samples are not exposed. Includes
    ``coverage_pct`` (how much of the window the station was actually reporting)
    and the owner's thresholds. For the night's summary use
    ``get_environment_night``. Times are local. Read-only."""
    from vitals.services import environment_context

    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.history_view(
            session, start=start, end=end, granularity=granularity, limit=limit
        )


@gated("environment")
async def get_environment_night(on_date: Optional[str] = None) -> dict:
    """Returns one night of the bedroom's air: the window 00:00–12:00 local of
    ``on_date`` (default today — which is *last night*, the one that ended this
    morning), with CO2 median / p90 / max, the minutes spent at or above the warn
    and bad lines, temperature and humidity ranges, and ``coverage_pct`` — how much
    of the window the station reported; a low value is a gap in the data, not a
    clean night. Includes the owner's sleeping thresholds. A night with no station
    data comes back with ``samples: 0`` and a note. Read-only."""
    from vitals.services import environment_context

    parsed = _parse_date(on_date, today_local(), field="on_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.night_view(session, parsed)


@gated("environment")
async def get_environment_vs_sleep(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict:
    """One row per night (the date you woke up; YYYY-MM-DD, both ends inclusive,
    default the last 14, max 31): the bedroom's air — coverage_pct, CO2
    median/p90/max, minutes at or above the warn line, temperature range, mean
    humidity — next to that night's Garmin sleep: score, total/deep/REM minutes,
    awakenings, HRV, resting and sleeping HR, respiration. ``columns`` names the
    ``rows``; a missing side is null. Below 80% coverage the air numbers describe
    only part of the night. Same-night co-occurrence, not cause. Read-only."""
    from vitals.services import environment_context

    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.nights_with_sleep(session, start=start, end=end)


@gated("environment")
async def get_environment_alerts(hours: int = 24) -> dict:
    """Returns the bedroom-air alerts that fired in the last ``hours`` (default 24,
    max 168) — too stuffy, too hot or cold, too dry or humid, station silent — each
    with its key, when it started and ended (``ongoing`` if still open), how long it
    lasted, and the peak the reading reached. Newest first; ``active`` counts the
    ones still open. Read-only."""
    from vitals.services import environment_context

    session_factory = get_session_factory()
    async with session_factory() as session:
        return await environment_context.alerts_view(session, hours=hours)


@gated("environment")
async def get_environment_settings() -> dict:
    """Returns the bedroom station's settings as the owner set them: the CO2
    zones (good < ``co2_ok_max`` ≤ ok < ``co2_warn`` ≤ warn < ``co2_bad`` ≤ bad,
    ppm), the day comfort and sleeping temperature ranges (°C), the humidity
    comfort band and the wider alert band (%), the ``night_window`` the night
    summaries use, and whether alerts fire at all (``alerts_enabled``) and go to
    Telegram (``alert_telegram``). Read-only; change with
    ``set_environment_settings``."""
    from vitals.services.environment import settings as env_settings

    session_factory = get_session_factory()
    async with session_factory() as session:
        return (await env_settings.get_settings(session)).to_dict()


@gated("environment")
async def set_environment_settings(
    co2_ok_max: Optional[int] = None,
    co2_warn: Optional[int] = None,
    co2_bad: Optional[int] = None,
    co2_good_max: Optional[int] = None,
    temp_day_min: Optional[float] = None,
    temp_day_max: Optional[float] = None,
    temp_sleep_min: Optional[float] = None,
    temp_sleep_max: Optional[float] = None,
    rh_min: Optional[float] = None,
    rh_max: Optional[float] = None,
    rh_alert_low: Optional[float] = None,
    rh_alert_high: Optional[float] = None,
    night_start: Optional[str] = None,
    night_end: Optional[str] = None,
    alerts_enabled: Optional[bool] = None,
    alert_telegram: Optional[bool] = None,
) -> dict:
    """Changes the bedroom station's thresholds and alert switches — the
    station card in Settings. Only the fields you pass change (see
    ``get_environment_settings`` for their meaning; ``night_start`` /
    ``night_end`` are HH:MM). As in the app, out-of-range values are clamped and
    the zones kept in order (CO2 400–5000 ppm, temperature −10…45 °C, humidity
    0–100 %) rather than rejected — the result is what was actually stored.
    WRITE tool."""
    from vitals.services.environment import settings as env_settings

    resolved_co2_ok = co2_good_max if co2_good_max is not None else co2_ok_max
    patch = {k: v for k, v in {
        "co2_ok_max": resolved_co2_ok, "co2_warn": co2_warn, "co2_bad": co2_bad,
        "temp_day_min": temp_day_min, "temp_day_max": temp_day_max,
        "temp_sleep_min": temp_sleep_min, "temp_sleep_max": temp_sleep_max,
        "rh_min": rh_min, "rh_max": rh_max,
        "rh_alert_low": rh_alert_low, "rh_alert_high": rh_alert_high,
        "alerts_enabled": alerts_enabled, "alert_telegram": alert_telegram,
    }.items() if v is not None}
    window = {k: v for k, v in {"start": night_start, "end": night_end}.items() if v is not None}
    if window:
        patch["night_window"] = window
    if not patch:
        return {"error": "nothing to change — pass at least one field"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        saved = await env_settings.set_settings(session, patch)
        await session.commit()
        return saved.to_dict()


# ── Consolidated read tool ───────────────────────────────────────────────────
_ENV_VIEWS = {
    ("series", False): (get_environment_series, None),
    ("live", False): (get_environment_live, None),
    ("night", False): (get_environment_night, None),
    ("vs_sleep", False): (get_environment_vs_sleep, None),
    ("alerts", False): (get_environment_alerts, None),
    ("settings", False): (get_environment_settings, None),
}


@tool(READ, module="environment")
@gated("environment")
async def get_environment(
    view: str = "series",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: Optional[str] = None,
    limit: Optional[int] = None,
    on_date: Optional[str] = None,
    hours: Optional[int] = None,
) -> dict:
    """Bedroom air station (CO2 ppm, temperature °C, humidity %). Times are local.

    ``view``:
      * ``series`` (default) — history over whole local days (YYYY-MM-DD, both
        ends inclusive) as ``columns`` + ``rows`` + ``coverage_pct`` + thresholds.
        ``granularity`` is ``hour`` (default, last 7d, max 31d) or ``minute``
        (default today, max 2d); ``limit`` default 800, max 3000 (truncation is
        flagged).
      * ``live`` — current reading, CO2 zone (good/ok/warn/bad), ppm/h trend,
        station online/stale/offline status and thresholds.
      * ``night`` — one night (00:00–12:00 local of ``on_date``, default today =
        last night): CO2 median/p90/max, minutes above warn/bad, temp/humidity
        ranges and ``coverage_pct``.
      * ``vs_sleep`` — per-night air summary beside Garmin sleep metrics
        (``start_date``/``end_date``, default last 14d, max 31d). Same-night
        co-occurrence, not cause.
      * ``alerts`` — bedroom-air alerts from the last ``hours`` (default 24, max
        168), newest first.
      * ``settings`` — thresholds, night window and alert switches (change with
        ``update_settings(section="environment")``)."""
    args = dict(
        start_date=start_date, end_date=end_date, granularity=granularity,
        limit=limit, on_date=on_date, hours=hours,
    )
    return await dispatch("get_environment", "view", view, _ENV_VIEWS, args)
