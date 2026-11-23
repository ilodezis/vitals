"""Signals, day context and the proactive Telegram layer."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from vitals.enums import Source
from vitals.models import (
    DayContext,
)
from vitals.utils.timeutils import today_local
from web.routers.mcp import _core
from web.routers.mcp._core import (
    READ, WRITE, _parse_date, gated, get_session_factory, dispatch, serialize_row, serialize_written, tool,
)

# ── Signals tools (free-text capture — optional module) ───────────────────────
async def list_signals(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    key: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Retrieves signals — the owner's own words about how a day felt, parsed into
    rows: states ("энергии ноль"), symptoms ("голова раскалывается"), exposures
    ("кофе в 22"). This is the domain that *explains* the Garmin numbers. Filter by
    ``kind`` (state/symptom/exposure) and/or ``key`` (matches every stored spelling
    that folds to it, e.g. ``sleepiness`` also finds ``sleepy_af``). Rows the owner
    flagged as misparsed are excluded. Newest first, most recent 200 by default."""
    from vitals.services import signals_service

    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        rows = await signals_service.list_signals(
            session, key=key, kind=kind, start=start, end=end, limit=limit
        )
        return [serialize_row(r) for r in rows]


@gated("signals")
async def log_signal(
    key: str,
    kind: str,
    value_num: Optional[float] = None,
    unit: Optional[str] = None,
    note: Optional[str] = None,
    at_time: Optional[str] = None,
    on_date: Optional[str] = None,
) -> dict:
    """Records one signal — a state, symptom or exposure the owner mentioned in
    conversation. ``kind`` must be state, symptom or exposure; ``key`` is a short
    slug (``headache``, ``caffeine_late``); ``value_num`` is intensity 1-5 for
    state/symptom or an amount for exposure; ``at_time`` is HH:MM (matters for
    exposures — "кофе в 22" only means something with the hour attached).
    WRITE tool — saved immediately."""
    from vitals.services import signals_service

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    async with session_factory() as session:
        rows = await signals_service.create_signals(
            session,
            items=[{
                "kind": kind, "key": key, "value_num": value_num,
                "unit": unit, "note": note, "at_time": at_time,
            }],
            on_date=parsed_date,
            source=Source.MCP.value,
        )
        # create_signals drops unusable rows silently (it batch-parses LLM output,
        # where one bad fact must not cost the message). A single-row tool call has
        # no such batch to protect — an empty result means this call was rejected.
        if not rows:
            return {"error": "kind must be state, symptom or exposure, and key must be non-empty"}
        await session.commit()
        return await serialize_written(session, rows[0])


@gated("signals")
async def mark_signal_misparse(batch_id: str) -> dict:
    """Flags every signal parsed out of one message as misparsed — the "не то"
    button. The rows and the raw text stay, they just drop out of ``get_signals``
    and out of the charts. ``batch_id`` is the field shared by all rows from the
    same message. WRITE tool — immediate."""
    from vitals.services import signals_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        marked = await signals_service.mark_misparse(session, batch_id)
        await session.commit()
        return {"marked": marked, "batch_id": batch_id}


async def get_day_context(
    start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100
) -> list[dict]:
    """Retrieves per-day context — what kind of day it was (remote/office, gym or
    not, workload), as answered by the owner or guessed by the week template
    (``planned``). One row per date, newest first. Read this before explaining a
    day's Garmin numbers: a heavy office day and a rest day at home look the same
    in the metrics and mean opposite things."""
    session_factory = get_session_factory()
    start = _parse_date(start_date, field="start_date")
    end = _parse_date(end_date, field="end_date")

    async with session_factory() as session:
        stmt = select(DayContext)
        if start:
            stmt = stmt.where(DayContext.date >= start)
        if end:
            stmt = stmt.where(DayContext.date <= end)
        stmt = stmt.order_by(DayContext.date.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [serialize_row(r) for r in rows]


@gated("signals")
async def log_day_context(answers: dict, on_date: Optional[str] = None) -> dict:
    """Records what kind of day it was — the same answers the owner taps in
    Telegram, when he says them here instead ("сегодня удалёнка, зала не будет").
    Keys: ``where`` (office/remote/off), ``gym`` (true/false), ``load``
    (light/normal/heavy — about a day already spent, not a plan). Only the keys
    you pass are changed, and the week template's own guess is kept beside the
    answer rather than overwritten. ``on_date`` defaults to today. WRITE tool."""
    from vitals.services.proactive import day_plan

    session_factory = get_session_factory()
    parsed_date = _parse_date(on_date, today_local(), field="on_date")

    legal = "; ".join(f"{q.key}: {list(q.labels)}" for q in day_plan.QUESTIONS)
    if not answers:
        return {"error": f"answers must contain at least one of — {legal}"}
    for key, value in answers.items():
        question = day_plan.QUESTIONS_BY_KEY.get(key)
        # Validated before anything is written: half-applied answers would leave
        # the day in a state neither the owner nor the template ever produced.
        if question is None or value not in question.labels:
            return {"error": f"{key}={value!r} is not a day-context answer — {legal}"}

    async with session_factory() as session:
        for key, value in answers.items():
            row = await day_plan.record_answer(session, parsed_date, key, value)
        await session.commit()
        return await serialize_written(session, row)


async def get_proactive_state(limit: int = 10) -> dict:
    """Retrieves the state of the proactive Telegram layer: whether it is on, its
    settings (message times, daily budget, which nudge categories are allowed), the
    week template (what each weekday is assumed to be until the owner says
    otherwise), and the last messages the bot actually sent. Read this before
    explaining why the bot did or didn't say something. READ tool — change the
    settings with ``set_proactive_settings``, the week template with
    ``set_week_template``."""
    from vitals.models.proactive import Notification
    from vitals.services.proactive import day_plan, prefs

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Notification).order_by(Notification.sent_at.desc()).limit(limit)
        sent = (await session.execute(stmt)).scalars().all()
        return {
            "enabled": await prefs.bot_enabled(session),
            "prefs": await prefs.get_prefs(session),
            "week_template": await day_plan.get_week_template(session),
            "recent_notifications": [serialize_row(n) for n in sent],
        }




async def set_proactive_settings(
    brief_time: Optional[str] = None,
    evening_time: Optional[str] = None,
    skincare_morning_time: Optional[str] = None,
    skincare_evening_time: Optional[str] = None,
    quiet_start: Optional[str] = None,
    quiet_end: Optional[str] = None,
    daily_budget: Optional[int] = None,
    nudges: Optional[dict] = None,
    garmin_sync_hours: Optional[int] = None,
    garmin_weight_export_minutes: Optional[int] = None,
    garmin_weight_max_age_days: Optional[int] = None,
    pulse_seconds: Optional[int] = None,
    pulse_start_hour: Optional[int] = None,
    pulse_end_hour: Optional[int] = None,
) -> dict:
    """Changes how the Telegram bot behaves — the Notifications card in Settings,
    applied the same way (the scheduler is re-timed at once, no restart). Only
    the fields you pass change; read the current values with
    ``get_proactive_state``.

    Times are HH:MM local: ``brief_time`` (morning brief), ``evening_time``
    (evening block), ``skincare_morning_time`` / ``skincare_evening_time`` (the
    skincare checklist messages), ``quiet_start``–``quiet_end`` (no self-initiated
    messages). ``daily_budget`` caps self-initiated messages a day (1–12).
    ``nudges`` switches categories on/off, e.g. ``{"activity": false,
    "skincare": true}`` — categories: activity, nutrition, data, environment,
    skincare (only those you name change). Data freshness: ``garmin_sync_hours``
    (1–24), ``pulse_seconds`` (60–3600, 0 = light pulse off) within
    ``pulse_start_hour``–``pulse_end_hour``; Garmin weight export cadence
    ``garmin_weight_export_minutes`` (5–1440) and ``garmin_weight_max_age_days``
    (1–30). Out-of-range values are clamped, as in the app — ``adjusted: true``
    says the stored result differs from what was asked. Switching the whole bot
    off is the signals module (``set_module("signals", False)``). WRITE tool."""
    from vitals.services.proactive import prefs
    from web.api.settings import apply_schedule

    current = await _proactive_current()
    raw = dict(current)
    given = False
    for key, value in {
        "brief_time": brief_time, "evening_time": evening_time,
        "skincare_morning_time": skincare_morning_time,
        "skincare_evening_time": skincare_evening_time,
        "quiet_start": quiet_start, "quiet_end": quiet_end, "daily_budget": daily_budget,
        "garmin_sync_hours": garmin_sync_hours,
        "garmin_weight_export_minutes": garmin_weight_export_minutes,
        "garmin_weight_max_age_days": garmin_weight_max_age_days,
        "pulse_seconds": pulse_seconds, "pulse_start_hour": pulse_start_hour,
        "pulse_end_hour": pulse_end_hour,
    }.items():
        if value is not None:
            raw[key] = value
            given = True
    if nudges is not None:
        given = True
        unknown = sorted(set(nudges) - set(prefs.NUDGE_CATEGORIES))
        if unknown:
            return {"error": f"unknown nudge categories {unknown} — use {', '.join(prefs.NUDGE_CATEGORIES)}"}
        raw["nudges"] = {**current["nudges"], **{k: bool(v) for k, v in nudges.items()}}
    if not given:
        return {"error": "nothing to change — pass at least one field"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        settings = await prefs.set_prefs(session, raw)
        await session.commit()
    if _core._HOST_APP is not None:
        apply_schedule(_core._HOST_APP, settings)
    return {"prefs": settings, "adjusted": raw != settings}


async def _proactive_current() -> dict:
    from vitals.services.proactive import prefs

    session_factory = get_session_factory()
    async with session_factory() as session:
        return await prefs.get_prefs(session)


@gated("signals")
async def set_week_template(template: dict) -> dict:
    """Stores the week template — what each weekday is assumed to be until the owner
    answers otherwise ("по вторникам я всегда на удалёнке"). Keys are "mon".."sun",
    each a dict of ``where`` (office/remote/off) and ``gym`` (true/false). Only the
    weekdays and keys you pass are changed; the rest keep their stored values. How
    heavy a day is can't be predicted from a weekday, so it isn't part of the
    template. WRITE tool — returns the full stored template."""
    from vitals.services.proactive import day_plan

    legal = "/".join(day_plan.WEEKDAYS)
    if not isinstance(template, dict) or not template:
        return {"error": f"template must be a dict of weekday → answers ({legal})"}
    unknown = sorted(k for k in template if k not in day_plan.WEEKDAYS)
    if unknown:
        return {"error": f"unknown weekday(s) {unknown} — use {legal}"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Merged onto the stored template, per day: the sanitizer fills an absent
        # weekday (and an absent key within one) from the neutral default, so a call
        # naming only Tuesday would otherwise reset the other six.
        merged = await day_plan.get_week_template(session)
        for day, values in template.items():
            if not isinstance(values, dict):
                return {"error": f"{day} must be a dict of answers, got {values!r}"}
            merged[day] = {**merged[day], **values}
        clean = await day_plan.set_week_template(session, merged)
        await session.commit()
        return clean


# ── Consolidated tools ───────────────────────────────────────────────────────
_SIGNAL_VIEWS = {
    ("signals", False): (list_signals, None),
    ("day_context", False): (get_day_context, None),
    ("proactive", False): (get_proactive_state, None),
}


@tool(READ, module="signals")
async def get_signals(
    view: str = "signals",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    kind: Optional[str] = None,
    key: Optional[str] = None,
    limit: Optional[int] = None,
):
    """What the owner said about his days, and the bot that asks.

    ``view``:
      * ``signals`` (default) — his own words parsed into rows: states ("no
        energy"), symptoms ("headache"), exposures ("coffee at 22"); the domain
        that *explains* the Garmin numbers. Filter by ``kind``
        (state/symptom/exposure) and/or ``key`` (matches every spelling that
        folds to it). Misparsed rows are excluded. Newest first, ``limit``
        default 200.
      * ``day_context`` — per day: remote/office, gym or not, workload, as
        answered or guessed from the week template (``planned``). Read it before
        explaining a day's Garmin numbers. ``limit`` default 100.
      * ``proactive`` — the Telegram layer: on/off, its settings (message times,
        daily budget, nudge categories), the week template and the last
        ``limit`` (default 10) messages it actually sent. Change them with
        ``update_settings``."""
    args = dict(start_date=start_date, end_date=end_date, kind=kind, key=key, limit=limit)
    return await dispatch("get_signals", "view", view, _SIGNAL_VIEWS, args)


_SIGNAL_ENTRIES = {
    ("signal", False): (log_signal, None),
    ("misparse", False): (mark_signal_misparse, None),
    ("day_context", False): (log_day_context, None),
}


@tool(WRITE, module="signals")
@gated("signals")
async def save_signal(
    entry: str = "signal",
    key: Optional[str] = None,
    kind: Optional[str] = None,
    value_num: Optional[float] = None,
    unit: Optional[str] = None,
    at_time: Optional[str] = None,
    on_date: Optional[str] = None,
    note: Optional[str] = None,
    batch_id: Optional[str] = None,
    answers: Optional[dict] = None,
) -> dict:
    """Records what the owner says about his day.

    ``entry``:
      * ``signal`` (default) — one state, symptom or exposure he mentioned:
        ``kind`` state | symptom | exposure, ``key`` a short slug ("headache",
        "caffeine_late"), ``value_num`` intensity 1–5 for a state/symptom or an
        amount for an exposure (+ ``unit``), ``at_time`` HH:MM (matters for
        exposures: "coffee at 22" means nothing without the hour), ``on_date``,
        ``note``.
      * ``misparse`` — flags every signal parsed out of one message (``batch_id``)
        as wrong; rows and raw text stay but drop out of reads and correlations.
      * ``day_context`` — what kind of day it was, the same answers he taps in
        Telegram: ``answers`` with ``where`` (office/remote/off), ``gym``
        (true/false), ``load`` (light/normal/heavy — about a day already spent);
        only the keys passed change. ``on_date`` defaults to today."""
    args = dict(
        key=key, kind=kind, value_num=value_num, unit=unit, at_time=at_time,
        on_date=on_date, note=note, batch_id=batch_id, answers=answers,
    )
    return await dispatch("save_signal", "entry", entry, _SIGNAL_ENTRIES, args)
