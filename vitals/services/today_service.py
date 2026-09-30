"""What today looks like — the assembly behind ``GET /today`` and
``GET /api/v1/today``.

The screen the app opens on. Everything here is *composition*: the morning
brief's cross-domain context, the weight chart series, the day's feed rows and
the alert ladder, all read through the services that already own them. A block
whose module is disabled is simply never assembled, so an instance running
"weight + Garmin only" gets a shorter screen instead of five empty cards.

There is one assembly, ``collect()``, and it speaks in values: numbers, dates,
kinds and tones. ``build()`` phrases it for the server-rendered page; the JSON API
hands it to the React screen, which phrases it in the reader's language. The
personal range (a corridor around his own fortnight) and the goal's forecast are
the only derived numbers here, and both are read off numbers the page already
prints — the trend and the baseline.

The narrative never waits on the LLM: when there is no ``daily_brief`` row for
today, a deterministic sentence is built from the same context the brief would
have been written from.
"""
from __future__ import annotations

import statistics
from datetime import date as date_type, datetime, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import DigestKind, Domain, MilestoneStatus, Severity
from vitals.i18n import decimal, t
from vitals.utils.timeutils import now_local, today_local

# How far off his own mean a number has to sit before the baseline is worth
# printing next to it. 5% is ~3 bpm of resting HR and ~4 points of sleep score —
# the same threshold the morning brief uses (proactive/compose.py).
_NOTABLE = 0.05

# How many rows the day's feed may hold before it stops being a glance.
_FEED_LIMIT = 12

# Metrics compared week over week, in the order they are offered to the card.
_RECOVERY_KEYS = ("sleep_score", "hrv_avg", "body_battery_high")

# Higher is better for everything here except weight and calories, which are
# handled on their own.
_HIGHER_IS_BETTER = frozenset(_RECOVERY_KEYS)

# A forecast that lands further out than this is arithmetic, not a plan: at a few
# grams a week the "date" is somewhere past any horizon the owner steers by.
_FORECAST_HORIZON_DAYS = 730


def _num(value: Any) -> str:
    """``86.0 → "86"``, ``86.13 → "86.1"`` — no trailing-zero noise on screen."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    return decimal(f"{round(value, 1):g}")


def _signed(value: Any) -> str:
    """A delta always carries its sign, with a real minus, not a hyphen."""
    try:
        value = round(float(value), 1)
    except (TypeError, ValueError):
        return str(value)
    text = f"+{value:g}" if value > 0 else f"{value:g}".replace("-", "−")
    return decimal(text)


def _mean(rows: Sequence[Any], key: str) -> Optional[float]:
    values = [v for v in (getattr(r, key, None) for r in rows) if v is not None]
    return sum(values) / len(values) if values else None


def _tone(delta: Optional[float], key: str) -> str:
    """Green/red for a change, blank when it is too small to mean anything."""
    if not delta:
        return ""
    if key in _HIGHER_IS_BETTER:
        return "good" if delta > 0 else "bad"
    if key == "weight":
        # Recomposition: the scale going down is the point.
        return "good" if delta < 0 else "bad"
    return ""


def _baseline_sub(value: Any, mean: Any) -> str:
    """``норма 85`` — or nothing when there is no norm yet, or today sits on it."""
    try:
        value, mean = float(value), float(mean)
    except (TypeError, ValueError):
        return ""
    if not mean or abs(value - mean) / abs(mean) < _NOTABLE:
        return ""
    return t("today.baseline", value=_num(mean))


def _as_date(value: Any) -> date_type:
    """An ISO string (what the brief's context carries) or a date, as a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    return date_type.fromisoformat(str(value)[:10])


def _spread(rows: Sequence[Any], key: str, today: date_type, *, window: int, minimum: int) -> Optional[float]:
    """Standard deviation of his own days *before* today, or ``None`` while there
    are too few of them for a range to mean anything — the same rows and the same
    threshold the baseline mean is taken from."""
    values = [
        v
        for v in (getattr(r, key, None) for r in rows if 0 < (today - r.date).days <= window)
        if v is not None
    ]
    return statistics.pstdev(values) if len(values) >= minimum else None


def _corridor(mean: Any, spread: Optional[float]) -> Optional[dict]:
    """His norm ± one standard deviation — the band a night is read against."""
    if mean is None or spread is None:
        return None
    return {"lo": round(mean - spread, 1), "hi": round(mean + spread, 1)}


def _forecast(
    current: float, target: float, trend: Optional[float], today: date_type, deadline: Optional[date_type]
) -> Optional[dict]:
    """The day the present trend meets the goal, and how far that sits from the
    deadline (positive: ahead of it). Linear, off the same kg/week the page prints;
    nothing when the trend is flat, moves away from the goal, or lands beyond the
    horizon."""
    if trend is None or trend >= 0 or current <= target:
        return None
    days = (current - target) / -trend * 7
    if days > _FORECAST_HORIZON_DAYS:
        return None
    lands = today + timedelta(days=round(days))
    return {"date": lands, "days_ahead": (deadline - lands).days if deadline else None}


def _raw_figure(key: str, value: Any, **extra: Any) -> dict:
    """One of the key figures, as values. Only the fields its own ``key`` uses are
    filled; the rest stay ``None``."""
    return {
        "key": key,
        "value": value,
        "tone": "",
        "trend": None,
        "baseline": None,
        "corridor": None,
        "sleep_seconds": None,
        "gained": None,
        **extra,
    }


def _raw_change(
    key: str, domain_key: str, before: float, after: float, corridor: Optional[dict] = None
) -> dict:
    return {
        "key": key,
        "domain_key": domain_key,
        "before": before,
        "after": after,
        "lo": corridor["lo"] if corridor else None,
        "hi": corridor["hi"] if corridor else None,
        "tone": _tone(round(after - before, 1), key),
    }


def _raw_feed(
    kind: str, dot: str, text: str = "", detail: str = "", *, time: str = "", value: Optional[float] = None
) -> dict:
    return {"time": time, "kind": kind, "dot": dot, "text": text, "detail": detail, "value": value}


# ── Phrasing, for the server-rendered page ───────────────────────────────────


def _phrase_figure(f: dict) -> dict:
    key, value = f["key"], f["value"]
    if key == "weight":
        unit = t("common.kg")
        sub = t("today.trend_week", value=_signed(f["trend"])) if f["trend"] is not None else ""
    elif key == "calories":
        unit = t("common.kcal")
        corridor = f["corridor"]
        sub = (
            t("today.corridor", min=_num(corridor["lo"]), max=_num(corridor["hi"]))
            if corridor
            else ""
        )
    else:
        unit = ""
        sub = _baseline_sub(value, f["baseline"])
    return {
        "key": key,
        "value": _num(value) if value is not None else "—",
        "unit": unit if value is not None else "",
        "tone": f["tone"],
        "sub": sub,
    }


def _phrase_change(c: dict) -> dict:
    delta = round(c["after"] - c["before"], 1)
    return {
        "key": c["key"],
        "domain_key": c["domain_key"],
        "href": "/" + c["domain_key"],
        "sentence": t("today.change_from_to", frm=_num(c["before"]), to=_num(c["after"])),
        "delta": _signed(delta),
        "tone": c["tone"],
    }


def _phrase_feed(row: dict) -> dict:
    kind, text, detail = row["kind"], row["text"], row["detail"]
    if kind == "meal":
        detail = t("today.src_meal", value=_num(row["value"])) if row["value"] else t("nav.nutrition")
    elif kind == "signal":
        detail = t("today.src_bot")
    elif kind == "brief":
        text, detail = t("today.brief_sent"), t("today.src_proactive")
    return {"time": row["time"], "dot": row["dot"], "text": text, "detail": detail}


def _phrase_goal(goal: Optional[dict]) -> Optional[dict]:
    if goal is None:
        return None
    from vitals.services import milestones_service

    done = goal["start_kg"] - goal["current_kg"]
    total = goal["start_kg"] - goal["target_kg"]
    pct = goal.get("pct")
    if pct is None:
        pct = milestones_service.weight_goal_pct(
            goal["start_kg"], goal["current_kg"], goal["target_kg"]
        )
    return {
        "name": goal["name"],
        "target": _num(goal["target_kg"]),
        "done": _num(done),
        "total": _num(total),
        "pct": pct if pct is not None else 0,
        "deadline": goal["deadline"].isoformat() if goal["deadline"] else None,
    }


async def collect(
    session: AsyncSession,
    *,
    enabled_modules: Optional[dict[str, bool]] = None,
    weigh_ins: bool = False,
) -> dict:
    """The day as values — everything ``today/index.html`` renders and the React
    screen draws, before any of it is phrased.

    ``weigh_ins`` is where the two consumers disagree: the server-rendered page
    never listed a weigh-in in the day's feed, the React screen adds one the moment
    a weight is saved and the refetch that follows has to keep it. The default is
    the old page's; the flag goes once that page does.
    """
    from vitals.services import (
        alerts_service,
        digest_service,
        garmin_service,
        nutrition_service,
        signals_service,
        timeline_service,
        weight_service,
    )
    from vitals.services.proactive import brief

    em = enabled_modules or {}
    today = today_local()
    cfg = load_config()

    ctx = await brief.build_context(session)
    weight = ctx.get("weight") or {}
    garmin = ctx.get("garmin") or {}
    baseline = garmin.get("baseline") or {}
    series = await weight_service.chart_series(session)
    daily = await garmin_service.list_daily(session, limit=brief._BASELINE_DAYS + 1)

    def corridor_of(key: str) -> Optional[dict]:
        spread = _spread(
            daily, key, today, window=brief._BASELINE_DAYS, minimum=brief._BASELINE_MIN_DAYS
        )
        return _corridor(baseline.get(key), spread)

    # ── Key figures ──────────────────────────────────────────────────────────
    trend = weight.get("trend_kg_per_week")
    figures = [_raw_figure("weight", weight.get("latest_kg"), trend=trend)]
    for key in _RECOVERY_KEYS:
        extra: dict[str, Any] = {}
        if key == "sleep_score":
            extra["sleep_seconds"] = garmin.get("sleep_seconds")
        elif key == "body_battery_high":
            extra["gained"] = garmin.get("body_battery_change")
        figures.append(
            _raw_figure(
                key,
                garmin.get(key),
                baseline=baseline.get(key),
                corridor=corridor_of(key),
                **extra,
            )
        )

    calories = None
    if em.get("nutrition"):
        summary = await nutrition_service.daily_summary(session, today, cfg)
        calories = summary["totals"]["calories"]
        goals = summary["goals"]
        lo, hi = goals["calories_min"], goals["calories_max"]
        figures.append(
            _raw_figure(
                "calories",
                calories,
                tone="" if summary["on_track"]["calories"] else "warn",
                corridor={"lo": lo, "hi": hi} if lo is not None and hi is not None else None,
            )
        )

    # ── What changed this week ───────────────────────────────────────────────
    # Two seven-day windows over the rows each domain already stores. Nothing is
    # derived that its own page doesn't derive too — the weight row is the same
    # noise-excluded 7-day mean the trend chart draws.
    changes: list[dict] = []
    ma7 = weight.get("ma7_kg")
    weekly_delta = series.get("weekly_delta")
    if ma7 is not None and weekly_delta is not None:
        changes.append(_raw_change("weight", "weight", ma7 - weekly_delta, ma7))

    this_week = [r for r in daily if 0 <= (today - r.date).days < 7]
    last_week = [r for r in daily if 7 <= (today - r.date).days < 14]
    for key in _RECOVERY_KEYS:
        now, before = _mean(this_week, key), _mean(last_week, key)
        if now is not None and before is not None:
            changes.append(_raw_change(key, "garmin", before, now, corridor_of(key)))

    if em.get("nutrition"):
        this_cal = await nutrition_service.nutrition_summary(
            session, today - timedelta(days=6), today, cfg
        )
        last_cal = await nutrition_service.nutrition_summary(
            session, today - timedelta(days=13), today - timedelta(days=7), cfg
        )
        if this_cal["days_with_logs"] and last_cal["days_with_logs"]:
            # Per *logged* day, not per calendar day: a week with three days
            # filled in would otherwise read as a crash in intake that never
            # happened.
            changes.append(
                _raw_change(
                    "calories",
                    "nutrition",
                    last_cal["totals"]["calories"] / last_cal["days_with_logs"],
                    this_cal["totals"]["calories"] / this_cal["days_with_logs"],
                )
            )

    # ── The day's feed ───────────────────────────────────────────────────────
    feed: list[dict] = []
    if em.get("timeline"):
        for e in await timeline_service.list_events(session, start=today, end=today):
            feed.append(
                _raw_feed("event", "good" if e.source == "manual" else "cool", e.title, e.detail or "")
            )
    if em.get("nutrition"):
        for m in await nutrition_service.list_meals_for_date(session, today):
            feed.append(
                _raw_feed(
                    "meal",
                    "good",
                    m.name,
                    time=m.eaten_at.strftime("%H:%M") if m.eaten_at else "",
                    value=m.calories,
                )
            )
    if em.get("signals"):
        for s in await signals_service.list_signals(session, start=today, end=today):
            feed.append(
                _raw_feed(
                    "signal",
                    "violet",
                    s.note or s.key,
                    time=s.at_time.strftime("%H:%M") if s.at_time else "",
                )
            )
    if weigh_ins:
        weigh_in = await weight_service.get_active_weight(session, today)
        if weigh_in is not None:
            # No time: ``created_at`` is stamped by the database in its own zone, so
            # a clock reading off it would be a guess.
            feed.append(_raw_feed("weight", "good", value=weigh_in.weight_kg))

    # ── The narrative ────────────────────────────────────────────────────────
    digest = await digest_service.latest_digest(session, kind=DigestKind.DAILY_BRIEF.value)
    brief_prose = _prose_from(digest) if digest is not None and digest.date == today else ""
    if brief_prose:
        narrative, narrative_source = brief_prose, "digest"
        # The one place a value on this page may carry the accent: it marks the
        # app's own message, not a measurement.
        feed.append(_raw_feed("brief", "amber"))
    else:
        narrative, narrative_source = _fallback_narrative(ctx, calories), "computed"

    # Timed rows first, in clock order; undated ones (a timeline flag, the brief)
    # sit under them rather than pretending to a time they don't have.
    feed.sort(key=lambda row: row["time"] or "99:99")
    # A day the owner touched every domain in — or a first run, where every seeded
    # goal and supplement carries today's date — must not turn this card into a
    # scrolling wall. The card is the day at a glance; the domains keep the full log.
    feed = feed[:_FEED_LIMIT]

    # ── Needs attention ──────────────────────────────────────────────────────
    attention = [
        {"severity": a.severity, "message": a.message, "domain": a.domain}
        for a in await alerts_service.list_active(session)
    ]
    advice = garmin.get("advice")
    if advice:
        # An interpretation of the numbers, not a failure — the quietest rung.
        attention.append(
            {"severity": Severity.NOTE.value, "message": advice, "domain": Domain.GARMIN.value}
        )

    latest_kg, latest_date = weight.get("latest_kg"), weight.get("latest_date")
    return {
        "date": today,
        "now": now_local(),
        "narrative": narrative,
        "narrative_source": narrative_source,
        "sync": _sync_rows(ctx, em),
        "figures": figures,
        "changes": changes[:4],
        "feed": feed,
        "attention": attention,
        "goal": await _goal(session, series, trend, today),
        "latest_weight": (
            {"kg": latest_kg, "date": _as_date(latest_date)}
            if latest_kg is not None and latest_date
            else None
        ),
    }


async def build(
    session: AsyncSession, *, enabled_modules: Optional[dict[str, bool]] = None
) -> dict:
    """Everything ``today/index.html`` renders, as one plain dict."""
    data = await collect(session, enabled_modules=enabled_modules)
    latest = data["latest_weight"]
    return {
        "date": data["date"],
        "time": data["now"].strftime("%H:%M"),
        "narrative": data["narrative"],
        "narrative_source": data["narrative_source"],
        "sync": [{"label": s["source"], "date": s["date"].isoformat()} for s in data["sync"]],
        "figures": [_phrase_figure(f) for f in data["figures"]],
        "changes": [_phrase_change(c) for c in data["changes"]],
        "feed": [_phrase_feed(row) for row in data["feed"]],
        "attention": [
            {"severity": a["severity"], "message": a["message"]} for a in data["attention"]
        ],
        "goal": _phrase_goal(data["goal"]),
        "latest_weight": latest["kg"] if latest else None,
    }


def _prose_from(row) -> str:
    """The model's paragraph out of a stored brief — and nothing else.

    ``content`` is the entire message that went to Telegram: the deterministic
    header (the very numbers this page prints as its key figures), then the day
    line, then the model's block last. Rendered whole it turned the hero into the
    whole message set in 38px, with every figure said twice.

    Where the prose starts is not guessed: the leading blocks are rebuilt from the
    context the row was stored with, exactly as ``generate_brief`` assembled them.
    ``model`` is set only when the model actually answered that morning, so it is
    also the honest test for "is there prose here at all" — a header-only brief
    falls through to the deterministic sentence instead of promoting a number line
    into the headline.
    """
    from vitals.services.proactive import compose, day_plan

    if not getattr(row, "model", None):
        return ""
    ctx = row.context_json or {}
    lead = len(compose.header_blocks(ctx))
    if day_plan.day_block(ctx.get("day")) is not None:
        lead += 1
    parts = (row.content or "").split("\n\n")
    if lead >= len(parts):
        # The stored message doesn't have the shape we just derived (hand-written
        # row, older format). Better a computed sentence than a mangled one.
        return ""
    return "\n\n".join(parts[lead:]).strip()


def _fallback_narrative(ctx: dict, calories: Optional[float]) -> str:
    """The sentence for a morning the model never wrote about.

    Same discipline as ``brief.narrative()``: a page must never sit waiting on
    the LLM, so the deterministic version is assembled from the context that was
    going to be handed to it anyway.
    """
    weight = ctx.get("weight") or {}
    garmin = ctx.get("garmin") or {}
    parts = []
    if weight.get("latest_kg") is not None:
        parts.append(t("today.said_weight", value=_num(weight["latest_kg"])))
    if weight.get("trend_kg_per_week") is not None:
        parts.append(t("today.said_trend", value=_signed(weight["trend_kg_per_week"])))
    for key in ("sleep_score", "hrv_avg"):
        if garmin.get(key) is not None:
            parts.append(t("today.said_" + key, value=_num(garmin[key])))
    if calories:
        parts.append(t("today.said_calories", value=_num(calories)))
    return ", ".join(parts) + "." if parts else t("today.said_nothing")


def _sync_rows(ctx: dict, em: dict) -> list[dict]:
    """Which integration last put something in the lake, and when."""
    rows = []
    garmin_date = (ctx.get("garmin") or {}).get("date")
    if garmin_date:
        rows.append({"source": "Garmin", "date": _as_date(garmin_date)})
    if em.get("hevy"):
        last = (ctx.get("hevy") or {}).get("last_workout")
        if last:
            rows.append({"source": "Hevy", "date": _as_date(last)})
    return rows


async def _goal(
    session: AsyncSession, series: dict, trend: Optional[float], today: date_type
) -> Optional[dict]:
    """The first weight goal, with where he started, where he is and where it lands.

    ``milestones_service.progress`` knows the target and where he is now but has
    no notion of where he started, and a bar needs all three — so the starting
    point is the first logged weight, which is also what "пройдено 11.2 из 17.5"
    means to the owner.
    """
    from vitals.services import milestones_service

    raw = series.get("raw") or []
    start = raw[0]["weight_kg"] if raw else None
    for card in await milestones_service.dashboard_cards(session):
        if card["domain"] != Domain.WEIGHT.value or card["current"] is None:
            continue
        if card["status"] != MilestoneStatus.ACTIVE.value:
            continue
        if card["target_value"] is None or start is None:
            continue
        pct = milestones_service.weight_goal_pct(start, card["current"], card["target_value"])
        if pct is None:
            continue
        deadline = _as_date(card["deadline"]) if card["deadline"] else None
        return {
            "name": card["name"],
            "start_kg": start,
            "current_kg": card["current"],
            "target_kg": card["target_value"],
            "pct": pct,
            "deadline": deadline,
            "forecast": _forecast(card["current"], card["target_value"], trend, today, deadline),
        }
    return None
