"""Nutrition domain service — meal logging with macro tracking.

CRUD over ``MealLog`` (multiple entries per day), plus daily/period summaries
with on-track checks against configurable protein/calorie goals.
"""
from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import Config
from vitals.enums import Domain, Source
from vitals.models.nutrition import DOMAIN, MealLog
from vitals.services import conflict_engine
from vitals.utils.timeutils import now_local, today_local


# ── Goals helper ─────────────────────────────────────────────────────────────

def get_goals(cfg: Config) -> dict[str, Any]:
    return {
        "protein_target_g": cfg.nutrition_protein_target_g,
        "calories_min": cfg.nutrition_calories_min,
        "calories_max": cfg.nutrition_calories_max,
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def log_meal(
    session: AsyncSession,
    *,
    on_date: date_type,
    name: str,
    eaten_at=None,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    note: Optional[str] = None,
    source: str = Source.MANUAL.value,
    override: bool = False,
) -> MealLog:
    await conflict_engine.enforce(
        session,
        Domain.NUTRITION.value,
        {"name": name, "calories": calories},
        override=override,
        entity_ref=f"meal:{on_date.isoformat()}",
    )
    if eaten_at is None:
        eaten_at = now_local().time()
    row = MealLog(
        date=on_date,
        domain=DOMAIN,
        source=source,
        name=name,
        eaten_at=eaten_at,
        calories=calories,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        note=note,
    )
    session.add(row)
    await session.flush()
    return row


async def update_meal(
    session: AsyncSession,
    meal_id: int,
    *,
    on_date: date_type,
    name: str,
    eaten_at=None,
    calories: Optional[float] = None,
    protein_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    note: Optional[str] = None,
) -> Optional[MealLog]:
    row = await session.get(MealLog, meal_id)
    if row is None:
        return None
    row.date = on_date
    row.name = name
    row.eaten_at = eaten_at
    row.calories = calories
    row.protein_g = protein_g
    row.fat_g = fat_g
    row.carbs_g = carbs_g
    row.note = note
    await session.flush()
    return row


async def delete_meal(session: AsyncSession, meal_id: int) -> bool:
    row = await session.get(MealLog, meal_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── Queries ──────────────────────────────────────────────────────────────────

async def list_meals_for_date(
    session: AsyncSession, on_date: date_type
) -> Sequence[MealLog]:
    result = await session.execute(
        select(MealLog)
        .where(MealLog.date == on_date)
        .order_by(MealLog.eaten_at.asc().nulls_last(), MealLog.id)
    )
    return result.scalars().all()


async def list_meals(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> Sequence[MealLog]:
    stmt = select(MealLog)
    if start is not None:
        stmt = stmt.where(MealLog.date >= start)
    if end is not None:
        stmt = stmt.where(MealLog.date <= end)
    stmt = stmt.order_by(MealLog.date.desc(), MealLog.eaten_at.asc().nulls_last(), MealLog.id)
    result = await session.execute(stmt)
    return result.scalars().all()


# ── Summaries ────────────────────────────────────────────────────────────────

def _sum_macros(meals: Sequence[MealLog]) -> dict[str, float]:
    return {
        "calories": sum(m.calories or 0 for m in meals),
        "protein_g": sum(m.protein_g or 0 for m in meals),
        "fat_g": sum(m.fat_g or 0 for m in meals),
        "carbs_g": sum(m.carbs_g or 0 for m in meals),
    }


# ── Conflict-engine resolver ──────────────────────────────────────────────────

async def resolve_today(session: AsyncSession) -> list[dict]:
    """Conflict-engine resolver: today's macro totals as a single match item —
    lets a rule reference e.g. {"calories": {"$gt": 4000}} against the running
    daily total, not just the one meal being logged right now."""
    meals = await list_meals_for_date(session, today_local())
    return [_sum_macros(meals)]


def _on_track(totals: dict[str, float], goals: dict[str, Any]) -> dict[str, bool]:
    cal = totals["calories"]
    return {
        "calories": goals["calories_min"] <= cal <= goals["calories_max"],
        "protein": totals["protein_g"] >= goals["protein_target_g"],
    }


async def daily_summary(
    session: AsyncSession, on_date: date_type, cfg: Config
) -> dict[str, Any]:
    meals = await list_meals_for_date(session, on_date)
    totals = _sum_macros(meals)
    goals = get_goals(cfg)
    return {
        "date": on_date.isoformat(),
        "totals": totals,
        "meal_count": len(meals),
        "goals": goals,
        "on_track": _on_track(totals, goals),
    }


async def nutrition_summary(
    session: AsyncSession,
    start: date_type,
    end: date_type,
    cfg: Config,
) -> dict[str, Any]:
    meals = await list_meals(session, start=start, end=end)
    totals = _sum_macros(meals)
    goals = get_goals(cfg)

    per_day: dict[date_type, list[MealLog]] = {}
    for m in meals:
        per_day.setdefault(m.date, []).append(m)

    daily = []
    d = start
    while d <= end:
        day_meals = per_day.get(d, [])
        day_totals = _sum_macros(day_meals)
        daily.append({
            "date": d.isoformat(),
            "meal_count": len(day_meals),
            **day_totals,
        })
        d += timedelta(days=1)

    days_with_logs = sum(1 for dm in daily if dm["meal_count"] > 0)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "totals": totals,
        "meal_count": len(meals),
        "days_with_logs": days_with_logs,
        "per_day": daily,
        "goals": goals,
        "on_track": _on_track(totals, goals) if days_with_logs == 1 else None,
    }
