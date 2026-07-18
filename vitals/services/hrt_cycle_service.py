"""HRT cycles — protocol plans, the schedule engine, and the active-release model.

Three concerns:

  * **Cycles** — CRUD over ``HrtCycle`` + its per-compound ``HrtCycleItem`` plans.
    Adding an open-ended cycle closes the previous open one the day before, so at
    most one protocol is "current" (mirrors GLP-1 dose phases).
  * **Schedule engine** — :func:`expand_schedule` turns an item's segment list
    (flat ``{dose, interval_days, duration_days}`` or a linear ramp with
    ``dose_start``/``dose_end``/``step``) into concrete planned administrations
    off a **fixed grid anchored at the cycle start** (a late real injection never
    shifts the grid). Fractional intervals (E3.5D) round to whole calendar days.
  * **Active-release model** — :func:`release_series` sums each administration's
    exponential decay (``0.5 ** (Δdays / half_life_days)``) scaled by the
    compound's active-hormone fraction, over actual logged doses plus (optionally)
    the active cycle's future plan. Illustrative only — real levels come from Labs.
"""
from __future__ import annotations

import math
from datetime import date as date_type, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import CycleKind, DoseUnit, Source
from vitals.models.hrt import DOMAIN, HrtCompound, HrtCycle, HrtCycleItem, HrtDose
from vitals.services import hrt_service
from vitals.utils.timeutils import today_local

# Guard against a pathological schedule (tiny interval, huge window) looping
# unboundedly — no real protocol produces this many shots in one segment.
_MAX_ADMIN_PER_SEGMENT = 100_000


def validate_schedule(schedule: object) -> list[dict]:
    """Validate a segment list and return a normalized copy (known keys only,
    numbers coerced). Raises ``ValueError`` with a per-segment message on bad
    shape. Write paths (form, MCP, template import) all funnel through this so a
    hand-crafted JSON payload can't smuggle a malformed segment into the DB."""
    if not isinstance(schedule, (list, tuple)) or not schedule:
        raise ValueError("schedule must be a non-empty list of segments")
    out: list[dict] = []
    last_idx = len(schedule) - 1
    for idx, seg in enumerate(schedule):
        where = f"segment {idx + 1}"
        if not isinstance(seg, dict):
            raise ValueError(f"{where}: must be an object")
        clean: dict = {}
        is_flat = seg.get("dose") is not None
        is_ramp = seg.get("dose_start") is not None or seg.get("dose_end") is not None
        if is_flat == is_ramp:
            raise ValueError(
                f"{where}: give either dose (flat) or dose_start+dose_end (ramp)"
            )
        try:
            if is_flat:
                clean["dose"] = float(seg["dose"])
                if clean["dose"] <= 0:
                    raise ValueError
            else:
                clean["dose_start"] = float(seg["dose_start"])
                clean["dose_end"] = float(seg["dose_end"])
                if clean["dose_start"] <= 0 or clean["dose_end"] <= 0:
                    raise ValueError
                if seg.get("step") is not None:
                    clean["step"] = abs(float(seg["step"]))
                if seg.get("step_every_days") is not None:
                    clean["step_every_days"] = float(seg["step_every_days"])
                    if clean["step_every_days"] <= 0:
                        raise ValueError
        except (TypeError, ValueError, KeyError):
            raise ValueError(f"{where}: doses must be positive numbers") from None
        try:
            interval = float(seg.get("interval_days") or 1)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: interval_days must be a positive number") from None
        if interval <= 0:
            raise ValueError(f"{where}: interval_days must be a positive number")
        clean["interval_days"] = interval
        duration = seg.get("duration_days")
        if duration is not None:
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                raise ValueError(f"{where}: duration_days must be a positive integer") from None
            if duration <= 0:
                raise ValueError(f"{where}: duration_days must be a positive integer")
            clean["duration_days"] = duration
        elif idx != last_idx:
            raise ValueError(f"{where}: only the last segment may omit duration_days")
        out.append(clean)
    return out


# ── Schedule engine (pure) ────────────────────────────────────────────────────
def _dose_at(seg: dict, elapsed_days: float, interval: float) -> float:
    """Dose for an administration ``elapsed_days`` into its segment. Flat segments
    return a constant; ramp segments step ``dose_start`` toward ``dose_end`` by
    ``step`` every ``step_every_days`` (or every interval), clamped to the range."""
    if seg.get("dose") is not None:
        return float(seg["dose"])
    start = float(seg["dose_start"])
    finish = float(seg["dose_end"])
    step = abs(float(seg.get("step") or 0))
    every = float(seg.get("step_every_days") or interval or 1)
    if every <= 0:
        every = interval or 1.0
    n = int(elapsed_days // every) if step > 0 else 0
    direction = 1.0 if finish >= start else -1.0
    value = start + direction * step * n
    low, high = (start, finish) if start <= finish else (finish, start)
    return max(low, min(high, value))


def expand_schedule(
    schedule: Optional[Sequence[dict]],
    anchor: date_type,
    start: date_type,
    end: date_type,
) -> list[tuple[date_type, float]]:
    """Expand a segment list into ``(date, dose)`` planned administrations within
    ``[start, end]``, off a fixed grid anchored at ``anchor``. Segments run in
    order; each occupies ``duration_days`` from where the previous ended. The last
    segment may omit ``duration_days`` to run open-ended to ``end``."""
    out: list[tuple[date_type, float]] = []
    if not schedule:
        return out
    total_window = (end - anchor).days
    seg_offset = 0
    last_idx = len(schedule) - 1
    for idx, seg in enumerate(schedule):
        interval = float(seg.get("interval_days") or 1)
        if interval <= 0:
            interval = 1.0
        duration = seg.get("duration_days")
        is_last = idx == last_idx
        if not duration and not is_last:
            # A non-last open segment is malformed (later segments would have no
            # start) — skip it rather than loop forever.
            continue
        seg_span = float(duration) if duration else float(total_window - seg_offset) + 1.0
        k = 0
        while k < _MAX_ADMIN_PER_SEGMENT:
            elapsed = k * interval
            if elapsed >= seg_span:
                break
            adm_date = anchor + timedelta(days=seg_offset + int(round(elapsed)))
            if adm_date > end:
                break
            if adm_date >= start:
                out.append((adm_date, _dose_at(seg, elapsed, interval)))
            k += 1
        if duration:
            seg_offset += int(duration)
        else:
            break
    return out


def expand_item_schedule(
    item: HrtCycleItem, anchor: date_type, start: date_type, end: date_type
) -> list[tuple[date_type, float]]:
    """Expand an item's schedule off the cycle anchor shifted by the item's own
    ``start_offset_days`` — a compound may join the protocol mid-cycle (e.g.
    winstrol from week 5). Every consumer (planned overlay, release curve,
    injection reminder) goes through here, so the offset applies uniformly."""
    offset = int(item.start_offset_days or 0)
    return expand_schedule(item.schedule, anchor + timedelta(days=offset), start, end)


# ── Cycle CRUD ────────────────────────────────────────────────────────────────
async def list_cycles(session: AsyncSession) -> Sequence[HrtCycle]:
    result = await session.execute(
        select(HrtCycle).where(HrtCycle.domain == DOMAIN).order_by(HrtCycle.start_date.desc())
    )
    return result.scalars().all()


async def active_cycle(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> Optional[HrtCycle]:
    """The cycle covering ``on_date`` (today by default). The newest match wins —
    ordered by start date then id, so a same-day supersede picks the one created
    last."""
    day = on_date or today_local()
    result = await session.execute(
        select(HrtCycle)
        .where(HrtCycle.domain == DOMAIN)
        .order_by(HrtCycle.start_date.desc(), HrtCycle.id.desc())
    )
    for cycle in result.scalars().all():
        if cycle.start_date <= day and (cycle.end_date is None or day <= cycle.end_date):
            return cycle
    return None


async def add_cycle(
    session: AsyncSession,
    *,
    kind: str,
    start_date: date_type,
    name: Optional[str] = None,
    end_date: Optional[date_type] = None,
    note: Optional[str] = None,
) -> HrtCycle:
    """Create a cycle. An open-ended one closes every other still-open cycle so at
    most one protocol is current — the day before the new one starts, but never
    before the old cycle's own start (a same-day supersede clamps to the start
    date, which is why the new cycle wins the ``active_cycle`` id tie-break)."""
    valid_kinds = {k.value for k in CycleKind}
    if kind not in valid_kinds:
        raise ValueError(f"kind must be one of: {', '.join(sorted(valid_kinds))}")
    if end_date is None:
        result = await session.execute(
            select(HrtCycle).where(HrtCycle.domain == DOMAIN, HrtCycle.end_date.is_(None))
        )
        for open_cycle in result.scalars().all():
            open_cycle.end_date = max(
                open_cycle.start_date, start_date - timedelta(days=1)
            )

    cycle = HrtCycle(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        name=name,
        kind=kind,
        start_date=start_date,
        end_date=end_date,
        note=note,
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def add_cycle_item(
    session: AsyncSession,
    cycle_id: int,
    *,
    compound_key: str,
    schedule: list[dict],
    unit: Optional[str] = None,
    start_offset_days: int = 0,
    note: Optional[str] = None,
) -> Optional[HrtCycleItem]:
    cycle = await session.get(HrtCycle, cycle_id)
    if cycle is None:
        return None
    key = (compound_key or "").strip()
    if not key:
        raise ValueError("compound_key is required")
    schedule = validate_schedule(schedule)
    offset = int(start_offset_days or 0)
    if offset < 0:
        raise ValueError("start_offset_days must be >= 0")
    compound = await hrt_service.get_compound(session, key)
    item = HrtCycleItem(
        cycle_id=cycle_id,
        compound_id=compound.id if compound else None,
        compound_key=key,
        unit=(unit or (compound.dose_unit if compound else DoseUnit.MG.value)),
        start_offset_days=offset,
        schedule=schedule,
        note=note,
    )
    session.add(item)
    await session.flush()
    return item


async def close_cycle(
    session: AsyncSession, cycle_id: int, *, end_date: date_type
) -> Optional[HrtCycle]:
    cycle = await session.get(HrtCycle, cycle_id)
    if cycle is None:
        return None
    cycle.end_date = end_date
    await session.flush()
    return cycle


async def delete_cycle(session: AsyncSession, cycle_id: int) -> bool:
    cycle = await session.get(HrtCycle, cycle_id)
    if cycle is None:
        return False
    await session.delete(cycle)
    await session.flush()
    return True


async def delete_cycle_item(session: AsyncSession, item_id: int) -> bool:
    item = await session.get(HrtCycleItem, item_id)
    if item is None:
        return False
    await session.delete(item)
    await session.flush()
    return True


# ── Planned administrations (from the active cycle) ───────────────────────────
async def planned_administrations(
    session: AsyncSession, *, start: date_type, end: date_type
) -> list[dict]:
    """Planned administrations from the active cycle within ``[start, end]``, one
    entry per shot: ``{date, compound_key, unit, dose}``. Empty when no cycle is
    active. Each item is anchored at the cycle's start (fixed grid)."""
    cycle = await active_cycle(session)
    if cycle is None:
        return []
    window_start = max(start, cycle.start_date)
    window_end = min(end, cycle.end_date) if cycle.end_date else end
    out: list[dict] = []
    for item in cycle.items:
        for adm_date, dose in expand_item_schedule(
            item, cycle.start_date, window_start, window_end
        ):
            out.append(
                {"date": adm_date, "compound_key": item.compound_key,
                 "unit": item.unit, "dose": dose}
            )
    out.sort(key=lambda a: a["date"])
    return out


# ── Active-release model ──────────────────────────────────────────────────────
def _active_mg(dose: float, unit: str, compound: Optional[HrtCompound]) -> Optional[float]:
    """Active-hormone mg an administration contributes to the release curve, or
    ``None`` if it can't be modelled (non-mg unit, or no half-life/fraction —
    e.g. GH in IU, peptides in mcg, or a free-text compound not in the catalog)."""
    if unit != DoseUnit.MG.value or compound is None:
        return None
    if compound.half_life_hours is None or not compound.half_life_hours:
        return None
    fraction = compound.active_fraction if compound.active_fraction is not None else 1.0
    return float(dose) * float(fraction)


async def _actual_contributions(
    session: AsyncSession, *, end: date_type
) -> list[tuple[date_type, float, float, str]]:
    """Actual logged doses up to ``end`` as ``(date, active_mg, half_life_days,
    compound_class)`` — only those that can be modelled (mg + known half-life)."""
    result = await session.execute(
        select(HrtDose, HrtCompound)
        .join(HrtCompound, HrtDose.compound_id == HrtCompound.id)
        .where(HrtDose.date <= end)
    )
    contribs: list[tuple[date_type, float, float, str]] = []
    for dose_row, compound in result:
        active = _active_mg(dose_row.dose, dose_row.unit, compound)
        if active is None:
            continue
        contribs.append(
            (dose_row.date, active, compound.half_life_hours / 24.0, compound.compound_class)
        )
    return contribs


async def _planned_contributions(
    session: AsyncSession, *, start: date_type, end: date_type
) -> list[tuple[date_type, float, float, str]]:
    """Future planned administrations (from the active cycle) as release
    contributions, resolving each item's compound for half-life/fraction."""
    cycle = await active_cycle(session)
    if cycle is None:
        return []
    contribs: list[tuple[date_type, float, float, str]] = []
    for item in cycle.items:
        compound = await hrt_service.get_compound(session, item.compound_key)
        window_start = max(start, cycle.start_date)
        window_end = min(end, cycle.end_date) if cycle.end_date else end
        for adm_date, dose in expand_item_schedule(
            item, cycle.start_date, window_start, window_end
        ):
            active = _active_mg(dose, item.unit, compound)
            if active is None:
                continue
            contribs.append(
                (adm_date, active, compound.half_life_hours / 24.0, compound.compound_class)
            )
    return contribs


async def release_series(
    session: AsyncSession,
    *,
    start: date_type,
    end: date_type,
    step_days: int = 1,
    include_planned: bool = True,
) -> list[dict]:
    """Daily active-hormone-in-body estimate over ``[start, end]``. Sums the
    exponential decay of every modelable administration (actual up to ``end``,
    plus future planned from the active cycle when ``include_planned``). Returns
    ``[{date, total_mg, by_class}]`` — total plus a per-compound-class split so a
    chart can stack testosterone vs 19-nors etc. Pure read; writes nothing."""
    contribs = await _actual_contributions(session, end=end)
    if include_planned:
        today = today_local()
        for adm_date, active, hl, cls in await _planned_contributions(
            session, start=today + timedelta(days=1), end=end
        ):
            contribs.append((adm_date, active, hl, cls))

    series: list[dict] = []
    day = start
    while day <= end:
        total = 0.0
        by_class: dict[str, float] = {}
        for adm_date, active, hl, cls in contribs:
            if adm_date > day or hl <= 0:
                continue
            remaining = active * math.pow(0.5, (day - adm_date).days / hl)
            total += remaining
            by_class[cls] = by_class.get(cls, 0.0) + remaining
        series.append({
            "date": day.isoformat(),
            "total_mg": round(total, 2),
            "by_class": {k: round(v, 2) for k, v in by_class.items()},
        })
        day += timedelta(days=step_days)
    return series
