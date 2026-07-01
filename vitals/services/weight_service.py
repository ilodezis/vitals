"""Weight & Body Composition service (Phase 1).

Owns the business rules for the weight domain:

  * **Manual-over-Garmin priority** — at most one *active* weight per date; a
    manual entry supersedes a Garmin import for the same date (the Garmin row is
    kept but flagged ``superseded`` — data-lake principle, never delete).
  * **Navy body-fat + LBM** computed on measurement write (LBM needs the day's
    active weight, so it's null until one exists).
  * **Noise ranges** excluded from the trend / projection.
  * **info alerts** — a noisy-weight period being active.
  * **Chart series** assembly for the dashboard (raw points + 7-day MA + LBM +
    optional goal projection).

Every mutating fn runs the conflict-engine override plumbing (``enforce``) so the
override UX is wired end-to-end even though real cross-domain weight rules land
with later modules.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import Config, load_config
from vitals.enums import Domain, Severity, Source
from vitals.i18n import t
from vitals.models.weight import (
    DOMAIN,
    BodyMeasurement,
    NoiseMarker,
    ProgressPhoto,
    WeightLog,
)
from vitals.services import alerts_service, conflict_engine
from vitals.services.analytics import exclude_ranges
from vitals.services.analytics.navy import lean_body_mass_kg, navy_body_fat_pct
from vitals.services.analytics.regression import fit_trend, project_date_for_value
from vitals.services.analytics.rolling import rolling_mean_by_date
from vitals.utils.timeutils import today_local

NOISE_ALERT_KEY = "weight.noisy_period_active"

# Cached at first use. NOTE: height/sex changes via Settings only take effect after
# a container restart (this cache + load_config() read env once) — unlike the login
# password, which is applied live. That's acceptable: body geometry rarely changes.
_config: Optional[Config] = None


def _body_config() -> tuple[float, str]:
    """(height_cm, sex) for the Navy formula, from config (cached; see note above)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config.height_cm, _config.sex


# A direct measurement — a manual entry or a body-composition scan (InBody/МедАсс)
# — outranks a passive device import (Garmin). Manual and scan tie at the top, so
# the latest of the two wins; Garmin never supersedes either (owner's rule:
# "Garmin overrides nothing").
_SOURCE_PRIORITY: dict[str, int] = {
    Source.MANUAL.value: 2,
    Source.BODY_SCAN.value: 2,
}


def _source_priority(source: str) -> int:
    """Priority of a weight source for the one-active-per-date invariant."""
    return _SOURCE_PRIORITY.get(source, 1)


# ── Weight logs ───────────────────────────────────────────────────────────────
async def get_active_weight(session: AsyncSession, on_date: date_type) -> Optional[WeightLog]:
    result = await session.execute(
        select(WeightLog).where(
            WeightLog.date == on_date, WeightLog.superseded.is_(False)
        )
    )
    return result.scalar_one_or_none()


async def log_weight(
    session: AsyncSession,
    *,
    on_date: date_type,
    weight_kg: float,
    source: str = Source.MANUAL.value,
    raw_payload_id: Optional[int] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> WeightLog:
    """Record a weight for a date, honouring manual-over-Garmin priority and the
    one-active-per-date invariant.

    May raise ``ConflictBlocked`` if a (future) cross-domain block rule fires
    without ``override``.
    """
    await conflict_engine.enforce(
        session,
        Domain.WEIGHT.value,
        {"weight_kg": weight_kg, "source": source},
        override=override,
        entity_ref=f"weight:{on_date.isoformat()}",
    )

    existing = await get_active_weight(session, on_date)

    if existing is not None and existing.source == source:
        # Same source, same date → latest reading replaces the previous in place.
        existing.weight_kg = weight_kg
        existing.raw_payload_id = raw_payload_id
        if note is not None:
            existing.note = note
        await session.flush()
        await _recompute_lbm_for_date(session, on_date, weight_kg)
        return existing

    insert_as_active = True
    if existing is not None:
        if _source_priority(source) >= _source_priority(existing.source):
            # New row outranks (or ties differently-sourced) the active one →
            # supersede it first to keep the partial-unique invariant.
            existing.superseded = True
            await session.flush()
        else:
            # Lower priority (e.g. Garmin arriving while a manual entry stands) →
            # keep the data but not active.
            insert_as_active = False

    row = WeightLog(
        date=on_date,
        domain=DOMAIN,
        source=source,
        weight_kg=weight_kg,
        raw_payload_id=raw_payload_id,
        note=note,
        superseded=not insert_as_active,
    )
    session.add(row)
    await session.flush()

    active_weight = weight_kg if insert_as_active else (
        existing.weight_kg if existing else None
    )
    if active_weight is not None:
        await _recompute_lbm_for_date(session, on_date, active_weight)
    return row


async def list_active_weights(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> Sequence[WeightLog]:
    stmt = select(WeightLog).where(WeightLog.superseded.is_(False))
    if start is not None:
        stmt = stmt.where(WeightLog.date >= start)
    if end is not None:
        stmt = stmt.where(WeightLog.date <= end)
    stmt = stmt.order_by(WeightLog.date)
    result = await session.execute(stmt)
    return result.scalars().all()


# ── Body measurements ─────────────────────────────────────────────────────────
async def upsert_body_measurement(
    session: AsyncSession,
    *,
    on_date: date_type,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> BodyMeasurement:
    """Create/update the day's measurement and (re)derive body-fat % + LBM.

    Partial merge: a field left ``None`` keeps whatever's already on file for
    the date instead of being blanked (e.g. MCP ``log_measurement`` is often
    called with just one of the three circumferences)."""
    await conflict_engine.enforce(
        session,
        Domain.WEIGHT.value,
        {"measurement": True},
        override=override,
        entity_ref=f"body_measurement:{on_date.isoformat()}",
    )

    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.date == on_date)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = BodyMeasurement(date=on_date, domain=DOMAIN, source=Source.MANUAL.value)
        session.add(row)

    effective_neck = neck_cm if neck_cm is not None else row.neck_cm
    effective_waist = waist_cm if waist_cm is not None else row.waist_cm
    effective_hips = hips_cm if hips_cm is not None else row.hips_cm

    height_cm, sex = _body_config()
    body_fat_pct = None
    if effective_neck and effective_waist:
        try:
            body_fat_pct = navy_body_fat_pct(
                waist_cm=effective_waist,
                neck_cm=effective_neck,
                height_cm=height_cm,
                sex=sex,
                hips_cm=effective_hips,
            )
        except ValueError:
            body_fat_pct = None

    lbm_kg = None
    if body_fat_pct is not None:
        active = await get_active_weight(session, on_date)
        if active is not None:
            lbm_kg = lean_body_mass_kg(active.weight_kg, body_fat_pct)

    row.neck_cm = effective_neck
    row.waist_cm = effective_waist
    row.hips_cm = effective_hips
    row.body_fat_pct = body_fat_pct
    row.lbm_kg = lbm_kg
    if note is not None:
        row.note = note
    await session.flush()
    return row


async def _recompute_lbm_for_date(
    session: AsyncSession, on_date: date_type, weight_kg: float
) -> None:
    """Refresh a measurement's LBM after the day's active weight changes."""
    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.date == on_date)
    )
    row = result.scalar_one_or_none()
    if row is not None and row.body_fat_pct is not None:
        row.lbm_kg = lean_body_mass_kg(weight_kg, row.body_fat_pct)
        await session.flush()


async def list_body_measurements(
    session: AsyncSession,
) -> Sequence[BodyMeasurement]:
    result = await session.execute(
        select(BodyMeasurement).order_by(BodyMeasurement.date)
    )
    return result.scalars().all()


# ── Noise markers ─────────────────────────────────────────────────────────────
async def add_noise_marker(
    session: AsyncSession,
    *,
    start_date: date_type,
    end_date: Optional[date_type] = None,
    reason: str,
    direction: Optional[str] = None,
) -> NoiseMarker:
    marker = NoiseMarker(
        domain=DOMAIN,
        source=Source.MANUAL.value,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        direction=direction,
    )
    session.add(marker)
    await session.flush()
    return marker


async def list_noise_markers(session: AsyncSession) -> Sequence[NoiseMarker]:
    result = await session.execute(
        select(NoiseMarker)
        .where(NoiseMarker.domain == DOMAIN)
        .order_by(NoiseMarker.start_date)
    )
    return result.scalars().all()


async def _noise_ranges(session: AsyncSession) -> list[tuple[date_type, Optional[date_type]]]:
    markers = await list_noise_markers(session)
    return [(m.start_date, m.end_date) for m in markers]


# ── Progress photos ───────────────────────────────────────────────────────────
async def add_progress_photo(
    session: AsyncSession,
    *,
    on_date: date_type,
    file_key: str,
    note: Optional[str] = None,
) -> ProgressPhoto:
    photo = ProgressPhoto(
        date=on_date, domain=DOMAIN, source=Source.MANUAL.value, file_key=file_key, note=note
    )
    session.add(photo)
    await session.flush()
    return photo


async def list_progress_photos(session: AsyncSession) -> Sequence[ProgressPhoto]:
    result = await session.execute(
        select(ProgressPhoto).order_by(ProgressPhoto.date.desc())
    )
    return result.scalars().all()


# ── Alerts ────────────────────────────────────────────────────────────────────
async def refresh_noise_alert(
    session: AsyncSession, *, on_date: Optional[date_type] = None
) -> Optional[object]:
    """Raise an ``info`` alert while today sits inside a noise range; resolve it
    once it doesn't. Idempotent (safe to call on every dashboard load / tick)."""
    today = on_date or today_local()
    ranges = await _noise_ranges(session)
    active_reason = None
    for marker in await list_noise_markers(session):
        end = marker.end_date
        if (end is None and today >= marker.start_date) or (
            end is not None and marker.start_date <= today <= end
        ):
            active_reason = marker.reason
            break

    if active_reason is not None:
        # Don't re-raise if the user already dismissed this alert today — it will
        # reappear automatically the next calendar day.
        if await alerts_service._was_dismissed_today(session, NOISE_ALERT_KEY, ""):
            return None
        return await alerts_service.raise_alert(
            session,
            domain=Domain.WEIGHT.value,
            severity=Severity.INFO.value,
            message=t("alert.weight_noisy", reason=active_reason),
            alert_key=NOISE_ALERT_KEY,
        )
    return await alerts_service.resolve_by_key(session, alert_key=NOISE_ALERT_KEY)


# ── Chart series ──────────────────────────────────────────────────────────────
async def chart_series(
    session: AsyncSession, *, goal_kg: Optional[float] = None, include_bia: bool = False
) -> dict:
    """Assemble everything the weight dashboard chart needs.

    Returns JSON-serialisable structures:
      * ``raw``        — [{date, weight_kg}] active points (secondary scatter)
      * ``trend_ma``   — [{date, weight_kg}] 7-day MA over noise-excluded points
      * ``lbm``        — [{date, lbm_kg}] from Navy measurements
      * ``noise``      — [{start, end}] ranges (for the chart annotation overlay)
      * ``projection`` — {target_kg, date} or None
      * ``trend``      — {slope_per_week} or None
      * ``bia``        — {bf:[{date,value}], lbm:[{date,value}]} from BIA scans,
                         only when ``include_bia`` (the body_comp module is on).
                         Coexists with the Navy ``lbm`` series — both are shown.
    """
    weights = await list_active_weights(session)
    raw_points = [(w.date, w.weight_kg) for w in weights]

    # Noise ranges fully drop out of the MA / regression / projection (a core
    # invariant): the trend must reflect real trajectory, not water-weight spikes.
    # The raw scatter keeps every point (shown under the noise overlay).
    ranges = await _noise_ranges(session)
    clean_points = exclude_ranges(raw_points, ranges)
    ma = rolling_mean_by_date(clean_points, window_days=7)

    measurements = await list_body_measurements(session)
    lbm_points = [
        {"date": m.date.isoformat(), "lbm_kg": m.lbm_kg}
        for m in measurements
        if m.lbm_kg is not None
    ]

    trend = fit_trend(raw_points, exclude=ranges)
    projection = None
    if goal_kg is not None:
        proj_date = project_date_for_value(raw_points, goal_kg, exclude=ranges)
        if proj_date is not None:
            projection = {"target_kg": goal_kg, "date": proj_date.isoformat()}

    phases = await _glp1_phase_overlays(session)

    # BIA overlay (InBody/МедАсс) — a second source for body-fat % / LBM shown
    # alongside the Navy series. Lazily imported so the weight module never hard-
    # depends on body_comp; only assembled when the module is enabled.
    bia = None
    if include_bia:
        from vitals.services import body_scan_service

        bia = await body_scan_service.bia_chart_points(session)

    return {
        "raw": [{"date": d.isoformat(), "weight_kg": v} for (d, v) in raw_points],
        "trend_ma": [{"date": d.isoformat(), "weight_kg": v} for (d, v) in ma],
        "lbm": lbm_points,
        "noise": [
            {"start": s.isoformat(), "end": (e.isoformat() if e else None)}
            for (s, e) in ranges
        ],
        "phases": phases,
        "projection": projection,
        "trend": (
            {"slope_per_week": round(trend.slope_per_week, 3)} if trend else None
        ),
        "bia": bia,
    }


async def _glp1_phase_overlays(session: AsyncSession) -> list[dict]:
    """GLP-1 dose phases for the chart overlay. Imported lazily so the weight
    module never depends on glp1 at import time (the cross-module link only
    exists for this one read, populated once Phase 2 lands)."""
    from vitals.models.glp1 import DOMAIN as GLP1_DOMAIN, DosePhase

    result = await session.execute(
        select(DosePhase)
        .where(DosePhase.domain == GLP1_DOMAIN)
        .order_by(DosePhase.start_date)
    )
    phases = result.scalars().all()
    return [
        {
            "start": p.start_date.isoformat(),
            "end": p.end_date.isoformat() if p.end_date else None,
            "drug": p.drug,
            "dose_mg": p.dose_mg,
            "label": f"{p.drug} {p.dose_mg:g} {t('common.mg')}",
        }
        for p in phases
    ]


# ── Deletion and Editing Helpers ──────────────────────────────────────────────
async def delete_weight_log(session: AsyncSession, log_id: int) -> bool:
    """Delete a weight log by ID. If it was active, reactivate the next highest
    priority log for that date (e.g. a Garmin import) and recompute LBM."""
    result = await session.execute(select(WeightLog).where(WeightLog.id == log_id))
    row = result.scalar_one_or_none()
    if not row:
        return False
    was_active = not row.superseded
    target_date = row.date
    await session.delete(row)
    await session.flush()

    if was_active:
        remaining = await session.execute(
            select(WeightLog)
            .where(WeightLog.date == target_date)
            .order_by(WeightLog.id.desc())
        )
        rows = remaining.scalars().all()
        # Reactivate the highest-priority source (manual/scan beat Garmin), and
        # among ties the newest row (id desc, already the scan order).
        next_row = max(
            rows, key=lambda r: (_source_priority(r.source), r.id), default=None
        )
        if next_row:
            next_row.superseded = False
            await session.flush()
            await _recompute_lbm_for_date(session, target_date, next_row.weight_kg)
        else:
            await _recompute_lbm_for_date_null(session, target_date)
    return True


async def _recompute_lbm_for_date_null(session: AsyncSession, on_date: date_type) -> None:
    """Clear LBM for a date because no active weight log remains."""
    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.date == on_date)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        row.lbm_kg = None
        await session.flush()


async def delete_body_measurement(session: AsyncSession, measurement_id: int) -> bool:
    """Delete a body measurement record by ID."""
    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.id == measurement_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def delete_progress_photo(session: AsyncSession, photo_id: int) -> Optional[str]:
    """Delete a progress photo record by ID. Returns the file_key of the deleted photo."""
    result = await session.execute(
        select(ProgressPhoto).where(ProgressPhoto.id == photo_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    file_key = row.file_key
    await session.delete(row)
    await session.flush()
    return file_key


async def delete_noise_marker(session: AsyncSession, marker_id: int) -> bool:
    """Delete a noise marker record by ID."""
    result = await session.execute(
        select(NoiseMarker).where(NoiseMarker.id == marker_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def update_weight_log(
    session: AsyncSession,
    log_id: int,
    *,
    on_date: date_type,
    weight_kg: float,
    note: Optional[str] = None,
    override: bool = False,
) -> Optional[WeightLog]:
    """Edit an existing weight log. If the date has changed, delete the old row
    (triggering reactivation of other rows) and insert a new log."""
    result = await session.execute(select(WeightLog).where(WeightLog.id == log_id))
    row = result.scalar_one_or_none()
    if not row:
        return None

    if row.date != on_date:
        source = row.source
        await delete_weight_log(session, log_id)
        return await log_weight(
            session,
            on_date=on_date,
            weight_kg=weight_kg,
            source=source,
            note=note,
            override=override,
        )
    else:
        await conflict_engine.enforce(
            session,
            Domain.WEIGHT.value,
            {"weight_kg": weight_kg, "source": row.source},
            override=override,
            entity_ref=f"weight:{on_date.isoformat()}",
        )
        row.weight_kg = weight_kg
        row.note = note
        await session.flush()
        await _recompute_lbm_for_date(session, on_date, weight_kg)
        return row


async def update_body_measurement(
    session: AsyncSession,
    measurement_id: int,
    *,
    on_date: date_type,
    neck_cm: Optional[float] = None,
    waist_cm: Optional[float] = None,
    hips_cm: Optional[float] = None,
    note: Optional[str] = None,
    override: bool = False,
) -> Optional[BodyMeasurement]:
    """Edit an existing body measurement. If the date has changed, delete the old row
    and upsert the new one."""
    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.id == measurement_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    if row.date != on_date:
        await session.delete(row)
        await session.flush()
        return await upsert_body_measurement(
            session,
            on_date=on_date,
            neck_cm=neck_cm,
            waist_cm=waist_cm,
            hips_cm=hips_cm,
            note=note,
            override=override,
        )
    else:
        return await upsert_body_measurement(
            session,
            on_date=on_date,
            neck_cm=neck_cm,
            waist_cm=waist_cm,
            hips_cm=hips_cm,
            note=note,
            override=override,
        )
