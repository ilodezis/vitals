"""The rail's status card — today's numbers, not today's plumbing.

The first version of this card reported how *fresh* each source was ("Labs · 99
days ago"), which is true every single day and useful on none of them. What the
chrome should answer without opening a page is "where am I right now": this
morning's weight and the week's direction, last night's sleep, today's intake,
the last session. Freshness only earns a line when a source has actually gone
quiet — then the number is replaced by how long it has been missing, which is the
one time that fact is worth the space.

Four small reads, one per domain, all against indexed date columns, so this is
cheap enough to run per page render (``web.deps.load_nav_status`` calls it for
HTML GETs only). Like ``modules_service.get_enabled_modules`` it NEVER raises —
the chrome must render even when a domain is unreadable, and a domain that
throws simply loses its row.

Two views of the same rows: ``rail_stats_raw`` returns plain values (what the
JSON API serves — the client formats them), ``rail_stats`` phrases those values
for the Jinja templates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.i18n import decimal, plural, t
from vitals.services.modules_service import CORE_KEYS
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)

# Days a source may go quiet before its row reports the silence instead of a
# number. Garmin syncs nightly; a training week with three rest days is normal.
_QUIET_AFTER = {"recovery": 2, "workouts": 5}


@dataclass(frozen=True)
class StatRow:
    key: str            # i18n suffix — stat.<key>
    value: str          # the headline number, already formatted
    sub: str = ""       # quiet note on the right (delta, target, secondary)
    tone: str = ""      # '' | 'good' | 'bad' | 'warn'


@dataclass(frozen=True)
class RailStat:
    """One row of the card as plain values — what ``StatRow`` phrases for Jinja.
    Only the fields of the row's own ``key`` are set; ``days_since`` also stands
    in for the number when a source has gone quiet (``recovery``)."""

    key: str                                # weight | recovery | nutrition | workouts
    tone: str = ""                          # '' | 'good' | 'bad' | 'warn'
    weight_kg: Optional[float] = None       # weight: latest reading
    delta_kg: Optional[float] = None        # weight: change since a week or more earlier
    sleep_seconds: Optional[int] = None     # recovery: last night
    readiness: Optional[int] = None         # recovery: training readiness
    calories: Optional[float] = None        # nutrition: eaten today
    calories_max: Optional[float] = None    # nutrition: the ceiling, when one is set
    protein_g: Optional[float] = None       # nutrition: protein eaten today
    days_since: Optional[int] = None        # workouts / quiet recovery: days without data


def _ago(days: int) -> str:
    """"today" / "yesterday" / "N days ago"."""
    if days <= 0:
        return t("sync.today")
    if days == 1:
        return t("sync.yesterday")
    word = plural(days, t("sync.day_one"), t("sync.day_few"), t("sync.day_many"))
    return t("sync.days_ago", n=days, word=word)


def _enabled(em: dict[str, bool], key: str) -> bool:
    return bool(em.get(key, key in CORE_KEYS))


async def _weight_stat(session: AsyncSession) -> Optional[RailStat]:
    """Latest weight, and the week's direction beside it — the direction is the
    reason to look, not the number."""
    from vitals.services import weight_service

    logs = await weight_service.list_active_weights(session)
    if not logs:
        return None
    latest = logs[-1]
    delta = await weight_service.weekly_trend_delta(session, logs=logs)
    tone = ""
    if delta is not None:
        tone = "good" if delta < 0 else ("bad" if delta > 0 else "")
    return RailStat(key="weight", tone=tone, weight_kg=latest.weight_kg, delta_kg=delta)


async def _recovery_stat(session: AsyncSession) -> Optional[RailStat]:
    """Last night's sleep, with training readiness as the note."""
    from vitals.services import garmin_service

    row = await garmin_service.latest_daily(session)
    if row is None:
        return None
    gap = (today_local() - row.date).days
    if gap > _QUIET_AFTER["recovery"]:
        return RailStat(key="recovery", tone="warn", days_since=gap)
    if not row.sleep_seconds:
        return None
    return RailStat(
        key="recovery",
        sleep_seconds=row.sleep_seconds,
        readiness=row.training_readiness,
    )


async def _nutrition_stat(session: AsyncSession) -> Optional[RailStat]:
    """Today's intake against the ceiling, protein beside it."""
    from vitals.config import load_config
    from vitals.services import nutrition_service

    summary = await nutrition_service.daily_summary(session, today_local(), load_config())
    if not summary["meal_count"]:
        return None
    totals, goals = summary["totals"], summary["goals"]
    ceiling = goals.get("calories_max") or None
    over = bool(ceiling and round(totals["calories"]) > ceiling)
    return RailStat(
        key="nutrition",
        tone="bad" if over else "",
        calories=totals["calories"],
        calories_max=ceiling,
        protein_g=totals["protein_g"],
    )


async def _workouts_stat(session: AsyncSession) -> Optional[RailStat]:
    """When the last session was — the only workout fact worth a nav rail."""
    from vitals.services import hevy_service

    last = await hevy_service.latest_workout_date(session)
    if last is None:
        return None
    gap = (today_local() - last).days
    return RailStat(
        key="workouts",
        tone="warn" if gap > _QUIET_AFTER["workouts"] else "",
        days_since=gap,
    )


# Row order = reading order in the card. Each entry is (module key that gates it,
# builder); a builder returning None means "nothing to say yet", not an error.
_ROWS = (
    ("weight", _weight_stat),
    ("garmin", _recovery_stat),
    ("nutrition", _nutrition_stat),
    ("hevy", _workouts_stat),
)


async def rail_stats_raw(
    session: AsyncSession, enabled: Optional[dict[str, bool]] = None
) -> list[RailStat]:
    """Today's readout for every enabled domain as plain values, in display
    order. Never raises."""
    em = enabled or {}
    rows: list[RailStat] = []
    for module_key, build in _ROWS:
        if not _enabled(em, module_key):
            continue
        try:
            row = await build(session)
        except Exception:
            logger.warning("nav status: %s row failed", module_key, exc_info=True)
            continue
        if row is not None:
            rows.append(row)
    return rows


def phrase(stat: RailStat) -> StatRow:
    """The row as the templates show it: the numbers already turned into words."""
    if stat.key == "weight":
        sub = ""
        if stat.delta_kg is not None:
            # U+2212 minus, not a hyphen: at 11px a hyphen next to a digit reads as
            # a dash in the label, and the sign is the whole point of this note.
            sub = decimal(f"{stat.delta_kg:+.1f}".replace("-", "−"))
        return StatRow(
            key="weight",
            value=f"{decimal(f'{stat.weight_kg:.1f}')} {t('common.kg')}",
            sub=sub,
            tone=stat.tone,
        )
    if stat.key == "recovery":
        if stat.days_since is not None:
            return StatRow(key="recovery", value=_ago(stat.days_since), tone=stat.tone)
        hours, minutes = divmod(stat.sleep_seconds // 60, 60)
        sub = t("stat.readiness", n=stat.readiness) if stat.readiness is not None else ""
        return StatRow(key="recovery", value=f"{hours}:{minutes:02d}", sub=sub)
    if stat.key == "nutrition":
        ceiling = stat.calories_max
        return StatRow(
            key="nutrition",
            value=(
                f"{round(stat.calories)}"
                f"{' / ' + str(round(ceiling)) if ceiling else ''} {t('common.kcal')}"
            ),
            sub=t("stat.protein", n=round(stat.protein_g), unit=t("common.g")),
            tone=stat.tone,
        )
    return StatRow(key=stat.key, value=_ago(stat.days_since), tone=stat.tone)


async def rail_stats(
    session: AsyncSession, enabled: Optional[dict[str, bool]] = None
) -> list[StatRow]:
    """Today's readout for every enabled domain, in display order. Never raises."""
    return [phrase(stat) for stat in await rail_stats_raw(session, enabled)]


def _enabled_keys(enabled: Optional[set[str] | dict[str, bool]]) -> set[str]:
    from vitals.services.modules_service import MODULE_REGISTRY

    if enabled is None:
        return set(MODULE_REGISTRY.keys())
    if isinstance(enabled, dict):
        on = {k for k, v in enabled.items() if v}
        for k in CORE_KEYS:
            if enabled.get(k, True):
                on.add(k)
        return on
    return set(enabled) | set(CORE_KEYS)


async def more_stats_raw(
    session: AsyncSession,
    enabled: Optional[set[str] | dict[str, bool]] = None,
) -> dict[str, dict]:
    """Raw per-module stats for the More screen (only enabled modules included)."""
    from vitals.config import load_config
    from vitals.services import (
        conflict_service,
        custom_charts_service,
        garmin_service,
        glp1_service,
        hevy_service,
        hrt_cycle_service,
        hrt_service,
        labs_service,
        modules_service,
        nutrition_service,
        supplements_service,
        weight_service,
    )

    on = _enabled_keys(enabled)
    today = today_local()
    out: dict[str, dict] = {}

    if "weight" in on:
        logs = await weight_service.list_active_weights(session)
        out["weight"] = {"weight_kg": round(logs[-1].weight_kg, 1) if logs else None}

    if "garmin" in on:
        daily = await garmin_service.latest_daily(session)
        out["garmin"] = {
            "sleep_score": daily.sleep_score if (daily and daily.sleep_score is not None) else None,
            "sleep_seconds": daily.sleep_seconds if (daily and daily.sleep_seconds is not None) else None,
            "hrv": round(daily.hrv_avg) if (daily and daily.hrv_avg is not None) else None,
        }

    if "hevy" in on:
        last = await hevy_service.latest_workout_date(session)
        out["hevy"] = {"days_since": max(0, (today - last).days) if last is not None else None}

    if "nutrition" in on:
        summary = await nutrition_service.daily_summary(session, today, load_config())
        cal = round(summary["totals"]["calories"]) if summary.get("meal_count") else None
        out["nutrition"] = {"calories": cal}

    if "glp1" in on:
        phase = await glp1_service.active_dose_phase(session, on_date=today)
        last_inj = await glp1_service.last_injection(session)
        days_to_next: Optional[int] = (
            ((last_inj.date + timedelta(days=7)) - today).days if last_inj is not None else None
        )
        out["glp1"] = {
            "drug": phase.drug if phase else (last_inj.drug if last_inj else None),
            "dose_mg": phase.dose_mg if phase else (last_inj.dose_mg if last_inj else None),
            "days_to_next": days_to_next,
        }

    if "hrt" in on:
        hrt_cyc = await hrt_cycle_service.active_cycle(session, on_date=today)
        prog = hrt_service._cycle_progress_data(hrt_cyc, today)
        out["hrt"] = {
            "week": prog["week"] if prog is not None else None,
            "weeks": prog["weeks"] if prog is not None else None,
        }

    if "labs" in on:
        latest_labs = await labs_service.latest_per_marker(session)
        if not latest_labs:
            out_of_range = 0
        else:
            latest_lab_date = max(r.date for r in latest_labs)
            out_of_range = sum(
                1
                for r in latest_labs
                if r.date == latest_lab_date and labs_service.is_out_of_range(r.flag)
            )
        out["labs"] = {"out_of_range": out_of_range}

    if "supplements" in on:
        active_supps = await supplements_service.list_supplements(session, active_only=True)
        out["supplements"] = {
            "active": len(active_supps),
            "active_count": len(active_supps),
        }

    if "interactions" in on:
        firing_ids = await conflict_service.get_firing_rule_ids(session)
        out["interactions"] = {"firing": len(firing_ids)}

    if "charts" in on:
        charts = await custom_charts_service.list_charts(session)
        out["charts"] = {"count": len(charts)}

    for mod in ("genetics", "skincare", "signals", "timeline", "reports"):
        if mod in on:
            out[mod] = {}

    out["share"] = {}
    out["settings"] = {
        "enabled": sum(1 for k in modules_service.MODULE_REGISTRY if k in on),
        "total": len(modules_service.MODULE_REGISTRY),
    }
    return out

