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

    today = today_local()
    logs = await weight_service.list_active_weights(session, start=today - timedelta(days=21))
    if not logs:
        return None
    latest = logs[-1]
    # Nearest reading at least a week older than the latest one — "a week ago"
    # has to survive gaps, and the day before yesterday is not a week.
    earlier = [w for w in logs if (latest.date - w.date).days >= 7]
    delta = latest.weight_kg - earlier[-1].weight_kg if earlier else None
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
