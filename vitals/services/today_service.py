"""What today looks like — the assembly behind ``GET /today``.

The screen the app opens on. Everything here is *composition*: the morning
brief's cross-domain context, the weight chart series, the day's feed rows and
the alert ladder, all read through the services that already own them. No new
metric is computed in this module; a block whose module is disabled is simply
never assembled, so an instance running "weight + Garmin only" gets a shorter
screen instead of five empty cards.

The narrative never waits on the LLM: when there is no ``daily_brief`` row for
today, a deterministic sentence is built from the same context the brief would
have been written from.
"""
from __future__ import annotations

from datetime import timedelta
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


def _figure(key: str, value: Any, *, unit: str = "", tone: str = "", sub: str = "") -> dict:
    return {
        "key": key,
        "value": _num(value) if value is not None else "—",
        "unit": unit if value is not None else "",
        "tone": tone,
        "sub": sub,
    }


def _change(key: str, domain_key: str, href: str, now: float, before: float) -> dict:
    delta = round(now - before, 1)
    return {
        "key": key,
        "domain_key": domain_key,
        "href": href,
        "sentence": t("today.change_from_to", frm=_num(before), to=_num(now)),
        "delta": _signed(delta),
        "tone": _tone(delta, key),
    }


async def build(
    session: AsyncSession, *, enabled_modules: Optional[dict[str, bool]] = None
) -> dict:
    """Everything ``today/index.html`` renders, as one plain dict."""
    from vitals.services import (
        alerts_service,
        digest_service,
        garmin_service,
        milestones_service,
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

    # ── Key figures ──────────────────────────────────────────────────────────
    trend = weight.get("trend_kg_per_week")
    figures = [
        _figure(
            "weight",
            weight.get("latest_kg"),
            unit=t("common.kg"),
            sub=t("today.trend_week", value=_signed(trend)) if trend is not None else "",
        )
    ]
    for key in _RECOVERY_KEYS:
        figures.append(
            _figure(key, garmin.get(key), sub=_baseline_sub(garmin.get(key), baseline.get(key)))
        )

    calories = None
    if em.get("nutrition"):
        summary = await nutrition_service.daily_summary(session, today, cfg)
        calories = summary["totals"]["calories"]
        goals = summary["goals"]
        figures.append(
            _figure(
                "calories",
                calories,
                unit=t("common.kcal"),
                tone="" if summary["on_track"]["calories"] else "warn",
                sub=t(
                    "today.corridor",
                    min=_num(goals["calories_min"]),
                    max=_num(goals["calories_max"]),
                ),
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
        changes.append(_change("weight", "weight", "/weight", ma7, ma7 - weekly_delta))

    daily = await garmin_service.list_daily(session, limit=14)
    this_week = [r for r in daily if 0 <= (today - r.date).days < 7]
    last_week = [r for r in daily if 7 <= (today - r.date).days < 14]
    for key in _RECOVERY_KEYS:
        now, before = _mean(this_week, key), _mean(last_week, key)
        if now is not None and before is not None:
            changes.append(_change(key, "garmin", "/garmin", now, before))

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
                _change(
                    "calories",
                    "nutrition",
                    "/nutrition",
                    this_cal["totals"]["calories"] / this_cal["days_with_logs"],
                    last_cal["totals"]["calories"] / last_cal["days_with_logs"],
                )
            )

    # ── The day's feed ───────────────────────────────────────────────────────
    feed: list[dict] = []
    if em.get("timeline"):
        for e in await timeline_service.list_events(session, start=today, end=today):
            feed.append({
                "time": "",
                "dot": "good" if e.source == "manual" else "cool",
                "text": e.title,
                "detail": e.detail or "",
            })
    if em.get("nutrition"):
        for m in await nutrition_service.list_meals_for_date(session, today):
            feed.append({
                "time": m.eaten_at.strftime("%H:%M") if m.eaten_at else "",
                "dot": "good",
                "text": m.name,
                "detail": t("today.src_meal", value=_num(m.calories)) if m.calories else t("nav.nutrition"),
            })
    if em.get("signals"):
        for s in await signals_service.list_signals(session, start=today, end=today):
            feed.append({
                "time": s.at_time.strftime("%H:%M") if s.at_time else "",
                "dot": "violet",
                "text": s.note or s.key,
                "detail": t("today.src_bot"),
            })

    # ── The narrative ────────────────────────────────────────────────────────
    digest = await digest_service.latest_digest(session, kind=DigestKind.DAILY_BRIEF.value)
    brief_prose = _prose_from(digest) if digest is not None and digest.date == today else ""
    if brief_prose:
        narrative, narrative_source = brief_prose, "digest"
        feed.append({
            "time": "",
            # The one place a value on this page may carry the accent: it marks
            # the app's own message, not a measurement.
            "dot": "amber",
            "text": t("today.brief_sent"),
            "detail": t("today.src_proactive"),
        })
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
        {"severity": a.severity, "message": a.message}
        for a in await alerts_service.list_active(session)
    ]
    advice = garmin.get("advice")
    if advice:
        # An interpretation of the numbers, not a failure — the quietest rung.
        attention.append({"severity": Severity.NOTE.value, "message": advice})

    return {
        "date": today,
        "time": now_local().strftime("%H:%M"),
        "narrative": narrative,
        "narrative_source": narrative_source,
        "sync": _sync_rows(ctx, em),
        "figures": figures,
        "changes": changes[:4],
        "feed": feed,
        "attention": attention,
        "goal": await _goal(session, series),
        "latest_weight": weight.get("latest_kg"),
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
        rows.append({"label": "Garmin", "date": garmin_date})
    if em.get("hevy"):
        last = (ctx.get("hevy") or {}).get("last_workout")
        if last:
            rows.append({"label": "Hevy", "date": last})
    return rows


async def _goal(session: AsyncSession, series: dict) -> Optional[dict]:
    """The first weight goal, as distance covered rather than distance left.

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
        total = start - card["target_value"]
        done = start - card["current"]
        if total <= 0:
            continue
        return {
            "name": card["name"],
            "target": _num(card["target_value"]),
            "done": _num(done),
            "total": _num(total),
            "pct": max(0, min(100, round(done / total * 100))),
            "deadline": card["deadline"],
        }
    return None
