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

import logging
import math
from datetime import date as date_type, timedelta
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

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
from vitals.utils import read_memo
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
    Source.MCP.value: 2,  # a weight he told Claude is a weight he entered
    Source.BODY_SCAN.value: 2,
}


def _source_priority(source: str) -> int:
    """Priority of a weight source for the one-active-per-date invariant."""
    return _SOURCE_PRIORITY.get(source, 1)


# Sanity bounds for the write path. These tools are reachable over MCP (an LLM),
# which bypasses the HTML form's min/max entirely, so a hallucinated 900 kg or a
# 0 has to be rejected here rather than land in the data lake — the same reasoning
# as ``glp1_service._validate_injection``, plus the upper bounds GLP-1 still lacks.
_WEIGHT_KG_RANGE = (20.0, 400.0)
_CIRCUMFERENCE_CM_RANGE = (10.0, 300.0)


def _check_range(name: str, value: Optional[float], bounds: tuple[float, float]) -> Optional[float]:
    """Reject a non-finite or out-of-range number, raising ``ValueError``. ``None``
    passes through untouched (an omitted optional field), so every field can be
    handed straight in."""
    if value is None:
        return None
    low, high = bounds
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g} (got {value!r})")
    return value


# ── Weight logs ───────────────────────────────────────────────────────────────
async def get_active_weight(session: AsyncSession, on_date: date_type) -> Optional[WeightLog]:
    result = await session.execute(
        select(WeightLog)
        .where(WeightLog.date == on_date, WeightLog.superseded.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_weight_log(session: AsyncSession, log_id: int) -> Optional[WeightLog]:
    """One weight row by id, superseded or not — what an edit starts from."""
    result = await session.execute(
        select(WeightLog).where(WeightLog.id == log_id).execution_options(populate_existing=True)
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
    without ``override``, or ``ValueError`` on an implausible weight.
    """
    _check_range("weight_kg", weight_kg, _WEIGHT_KG_RANGE)

    # Every active-weight writer participates in the Garmin outbox lock before
    # it changes local truth (including conflict-alert writes). The hook below
    # only reconciles local DB state and never performs network I/O.
    from vitals.services import garmin_weight_service

    await garmin_weight_service.lock_active_weight_change(session)
    await conflict_engine.enforce(
        session,
        Domain.WEIGHT.value,
        {"weight_kg": weight_kg, "source": source},
        override=override,
        entity_ref=f"weight:{on_date.isoformat()}",
    )

    existing = await get_active_weight(session, on_date)

    # A re-import of a fact we already hold is not a new reading. Garmin's daily
    # bundle carries the same weigh-in on every poll, so without this each sync
    # appended another identical row and superseded the last — a day accumulated
    # a dozen clones, and deleting the visible one just promoted its twin.
    if (
        existing is not None
        and existing.source == source
        and existing.weight_kg == weight_kg
    ):
        return existing

    # The active row can be a higher-priority manual measurement while an
    # identical Garmin import already sits underneath it.  Daily Garmin polls
    # must reuse that inactive fact too; otherwise each poll appends another
    # superseded clone even though the visible manual row never changes.
    if (
        existing is not None
        and _source_priority(source) < _source_priority(existing.source)
    ):
        duplicate = (
            await session.execute(
                select(WeightLog)
                .where(
                    WeightLog.date == on_date,
                    WeightLog.source == source,
                    WeightLog.weight_kg == weight_kg,
                )
                .order_by(WeightLog.id.desc())
                .execution_options(populate_existing=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return duplicate

    insert_as_active = True
    if existing is not None:
        if _source_priority(source) >= _source_priority(existing.source):
            # New row outranks (or ties — same source, same date) the active one →
            # supersede it first to keep the partial-unique invariant. The old row
            # is kept (flagged superseded), never overwritten: a re-entry or a
            # correction must not silently destroy the previous reading
            # (data-lake principle — never delete).
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
    if insert_as_active:
        await garmin_weight_service.handle_active_weight_changed(session)
    return row


async def list_active_weights(
    session: AsyncSession,
    *,
    start: Optional[date_type] = None,
    end: Optional[date_type] = None,
) -> Sequence[WeightLog]:
    """Active weigh-ins, oldest first. The whole history is read once per unit of
    work (several services on one screen ask for it, most of them for "everything up
    to a date"); a window with a start is cut from it when it is already here and
    read on its own otherwise."""
    held = read_memo.peek(session, _ACTIVE_WEIGHTS_MEMO)
    if held is None and start is None:
        held = await read_memo.remember(session, _ACTIVE_WEIGHTS_MEMO, lambda: _read_active_weights(session))
    if held is not None:
        # One active row per date (partial unique index), so the date order is total.
        return [
            w
            for w in held
            if (start is None or w.date >= start) and (end is None or w.date <= end)
        ]
    return await _read_active_weights(session, start=start, end=end)


_ACTIVE_WEIGHTS_MEMO = "weight_service.active_weights"


async def _read_active_weights(
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
    partial: bool = True,
) -> BodyMeasurement:
    """Create/update the day's measurement and (re)derive body-fat % + LBM.

    Partial merge (``partial=True``, the default): a field left ``None`` keeps
    whatever's already on file for the date instead of being blanked (e.g. MCP
    ``log_measurement`` is often called with just one of the three
    circumferences).

    ``partial=False`` means the caller is handing over the row's whole truth and
    ``None`` blanks the field. That is the HTML edit form: it always submits
    every field it renders, and FastAPI turns an emptied input into ``None`` —
    so under the merge the owner could never delete a value he had entered by
    mistake, it would silently come back."""
    _check_range("neck_cm", neck_cm, _CIRCUMFERENCE_CM_RANGE)
    _check_range("waist_cm", waist_cm, _CIRCUMFERENCE_CM_RANGE)
    _check_range("hips_cm", hips_cm, _CIRCUMFERENCE_CM_RANGE)
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

    if partial:
        effective_neck = neck_cm if neck_cm is not None else row.neck_cm
        effective_waist = waist_cm if waist_cm is not None else row.waist_cm
        effective_hips = hips_cm if hips_cm is not None else row.hips_cm
    else:
        effective_neck, effective_waist, effective_hips = neck_cm, waist_cm, hips_cm

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
    if note is not None or not partial:
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
    session: AsyncSession,
    *,
    goal_kg: Optional[float] = None,
    include_bia: bool = False,
    include_timeline: bool = False,
    include_glp1: bool = True,
    end: Optional[date_type] = None,
) -> dict:
    """Assemble everything the weight dashboard chart needs.

    Returns JSON-serialisable structures:
      * ``raw``        — [{date, weight_kg}] active points (secondary scatter)
      * ``trend_ma``   — [{date, weight_kg}] 7-day MA over noise-excluded points
      * ``lbm``        — [{date, lbm_kg}] from Navy measurements
      * ``noise``      — [{start, end}] ranges (for the chart annotation overlay)
      * ``projection`` — {target_kg, date} or None
      * ``trend``      — {slope_per_week} or None — the least-squares slope over
                         the WHOLE history, i.e. an average weekly rate, not the
                         last week's movement (see ``weekly_delta`` for that)
      * ``weekly_delta`` — kg moved over the last 7 days: the 7-day MA now minus
                         the 7-day MA a week ago, or None with under a week of data
      * ``bia``        — {bf:[{date,value}], lbm:[{date,value}]} from BIA scans,
                         only when ``include_bia`` (the body_comp module is on).
                         Coexists with the Navy ``lbm`` series — both are shown.
      * ``annotations`` — [{start, end?, label, tone, kind}] manual Timeline
                         flags for this domain (+ global ones), only when
                         ``include_timeline`` (the timeline module is on).
    """
    weights = await list_active_weights(session, end=end)
    raw_points = [(w.date, w.weight_kg) for w in weights]

    # Noise ranges fully drop out of the MA / regression / projection (a core
    # invariant): the trend must reflect real trajectory, not water-weight spikes.
    # The raw scatter keeps every point (shown under the noise overlay).
    ranges = [
        (start, range_end)
        for start, range_end in await _noise_ranges(session)
        if end is None or start <= end
    ]
    clean_points = exclude_ranges(raw_points, ranges)
    ma = rolling_mean_by_date(clean_points, window_days=7)

    measurements = [
        row
        for row in await list_body_measurements(session)
        if end is None or row.date <= end
    ]
    lbm_points = [
        {"date": m.date.isoformat(), "lbm_kg": m.lbm_kg}
        for m in measurements
        if m.lbm_kg is not None
    ]

    # Actual movement over the last 7 days, measured on the noise-excluded MA (so
    # a single water-weight day can't fake a kilo). Deliberately NOT the regression
    # slope: that's the average weekly rate across the entire history, which on a
    # long log reads as a wildly overstated "last week" number.
    weekly_delta = None
    if ma:
        last_date, last_ma = ma[-1]
        cutoff = last_date - timedelta(days=7)
        prior = [v for (d, v) in ma if d <= cutoff]
        if prior:
            weekly_delta = round(last_ma - prior[-1], 2)

    trend = fit_trend(raw_points, exclude=ranges)
    projection = None
    if goal_kg is not None:
        proj_date = project_date_for_value(raw_points, goal_kg, exclude=ranges)
        if proj_date is not None:
            projection = {"target_kg": goal_kg, "date": proj_date.isoformat()}

    phases = await _glp1_phase_overlays(session) if include_glp1 else []

    # BIA overlay (InBody/МедАсс) — a second source for body-fat % / LBM shown
    # alongside the Navy series. Lazily imported so the weight module never hard-
    # depends on body_comp; only assembled when the module is enabled.
    bia = None
    if include_bia:
        from vitals.services import body_scan_service

        bia = await body_scan_service.bia_chart_points(session)

    # Timeline flags (manual annotations) — lazy import, only when the
    # optional timeline module is on (a disabled module behaves as absent).
    annotations = None
    if include_timeline:
        from vitals.services import timeline_service

        annotations = await timeline_service.overlays_for(session, domain=DOMAIN)

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
        "weekly_delta": weekly_delta,
        "bia": bia,
        "annotations": annotations,
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
    # Classify active/superseded only after joining the shared outbox lock. A
    # concurrent deletion can reactivate a row that this reusable session loaded
    # earlier; populate_existing prevents the identity map from preserving that
    # stale classification. The lock also precedes any FK ``SET NULL`` flush,
    # keeping the global advisory→weight→outbox order consistent.
    from vitals.services import garmin_weight_service

    await garmin_weight_service.lock_active_weight_change(session)
    result = await session.execute(
        select(WeightLog)
        .where(WeightLog.id == log_id)
        .execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    was_active = not row.superseded
    target_date = row.date
    deleted_id = row.id
    deleted_weight_kg = row.weight_kg
    await session.delete(row)
    await session.flush()

    if was_active:
        remaining = await session.execute(
            select(WeightLog)
            .where(WeightLog.date == target_date)
            .order_by(WeightLog.id.desc())
            .execution_options(populate_existing=True)
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

        # Keep Garmin cleanup inside the same local transaction, but never make a
        # network call here. The export job will delete only a remote sample that
        # Vitals owns, and its monotonic cursor prevents an older date surfacing as
        # an accidental backfill after this row disappears.
        await garmin_weight_service.handle_active_weight_deleted(
            session,
            deleted_id=deleted_id,
            on_date=target_date,
            deleted_weight_kg=deleted_weight_kg,
            replacement=next_row,
        )
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
    _check_range("weight_kg", weight_kg, _WEIGHT_KG_RANGE)
    from vitals.services import garmin_weight_service

    await garmin_weight_service.lock_active_weight_change(session)
    result = await session.execute(
        select(WeightLog)
        .where(WeightLog.id == log_id)
        .execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    if row.date != on_date:
        source = row.source
        # The insert can be rejected by the cross-domain conflict engine.  Keep
        # the destructive half of the move in a savepoint so callers that turn
        # ConflictBlocked into a 409 cannot accidentally commit the deletion.
        async with session.begin_nested():
            await delete_weight_log(session, log_id)
            moved = await log_weight(
                session,
                on_date=on_date,
                weight_kg=weight_kg,
                source=source,
                note=note,
                override=override,
            )
        return moved
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
        # Editing a retained, superseded fact must not change body composition:
        # LBM is derived from the one active weight for the date.
        if not row.superseded:
            await _recompute_lbm_for_date(session, on_date, weight_kg)
            await garmin_weight_service.handle_active_weight_changed(session)
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
    partial: bool = True,
) -> Optional[BodyMeasurement]:
    """Edit an existing body measurement. If the date has changed, delete the old row
    and upsert the new one.

    ``partial`` carries the same meaning as in ``upsert_body_measurement``: the
    default keeps omitted fields (MCP), ``False`` lets the caller blank them
    (the HTML form)."""
    result = await session.execute(
        select(BodyMeasurement).where(BodyMeasurement.id == measurement_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    if row.date != on_date:
        if partial:
            # Carry the untouched fields off the old row *before* deleting it. The
            # partial merge in upsert_body_measurement reads the row on the target
            # date, which is empty here — so a caller that passed only one field (the
            # MCP edit tool routinely does) would otherwise blank the other two, and
            # body_fat_pct/lbm_kg derived from them, with no way to get them back.
            # Under partial=False the caller sent the whole row, so there is nothing
            # to carry: what it left empty it means to delete.
            neck_cm = neck_cm if neck_cm is not None else row.neck_cm
            waist_cm = waist_cm if waist_cm is not None else row.waist_cm
            hips_cm = hips_cm if hips_cm is not None else row.hips_cm
            note = note if note is not None else row.note
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
        partial=partial,
    )


# ── Shared Trend & Dose Delta Helpers ─────────────────────────────────────────
async def weekly_trend_delta(
    session: AsyncSession,
    *,
    logs: Optional[Sequence[WeightLog]] = None,
    end: Optional[date_type] = None,
) -> Optional[float]:
    """Noise-excluded linear regression slope (kg/week) across active weights."""
    weights = logs if logs is not None else await list_active_weights(session, end=end)
    raw_points = [(w.date, w.weight_kg) for w in weights]
    ranges = [
        (start, range_end)
        for start, range_end in await _noise_ranges(session)
        if end is None or start <= end
    ]
    trend = fit_trend(raw_points, exclude=ranges)
    return round(trend.slope_per_week, 3) if trend else None


async def dose_phase_delta(
    session: AsyncSession,
    phase: object,
    *,
    weights: Optional[Sequence[WeightLog]] = None,
    end: Optional[date_type] = None,
) -> Optional[float]:
    """Weight change (last - first, negative = weight loss) across a GLP-1 dose phase.

    ``None`` while the phase holds fewer than two weigh-ins: there is no change to
    report yet, and a zero would read as "the weight stood still".
    """
    if isinstance(phase, date_type):
        start_d: Optional[date_type] = phase
        end_d: Optional[date_type] = end
    elif isinstance(phase, dict):
        raw_s = phase.get("start_date") or phase.get("from_date") or phase.get("start")
        start_d = date_type.fromisoformat(raw_s) if isinstance(raw_s, str) else raw_s
        raw_e = phase.get("end_date") or phase.get("to_date") or phase.get("end")
        end_d = (
            (date_type.fromisoformat(raw_e) if isinstance(raw_e, str) else raw_e)
            if raw_e
            else end
        )
    else:
        start_d = getattr(phase, "start_date", None) or getattr(phase, "from_date", None)
        end_d = getattr(phase, "end_date", None) or getattr(phase, "to_date", None) or end
    if start_d is None:
        return None
    if weights is None:
        weights_on_dose = await list_active_weights(session, start=start_d, end=end_d)
    else:
        weights_on_dose = [
            w
            for w in weights
            if w.date >= start_d and (end_d is None or w.date <= end_d)
        ]
    if len(weights_on_dose) >= 2:
        return round(weights_on_dose[-1].weight_kg - weights_on_dose[0].weight_kg, 1)
    return None


def weeks_to_goal(
    current_kg: Optional[float], target_kg: float, per_week_kg: Optional[float]
) -> Optional[int]:
    """Whole weeks until the present trend meets a "get below" goal.

    ``None`` when there is nothing to extrapolate: no reading, no trend, a trend
    that is flat or moves away from the goal, or a goal already reached.
    """
    if current_kg is None or per_week_kg is None or per_week_kg >= 0 or current_kg <= target_kg:
        return None
    return max(1, round((current_kg - target_kg) / -per_week_kg))


def _norm_source(src: str) -> str:
    if src in ("garmin_api", "garmin"):
        return "garmin"
    if src in ("body_scan", "bia"):
        return "bia"
    return "manual"


def _superseded_by_source(src: Optional[str]) -> Optional[str]:
    if not src:
        return None
    if src in (Source.BODY_SCAN.value, "bia"):
        return Source.BODY_SCAN.value
    return Source.MANUAL.value


async def collect(
    session: AsyncSession,
    *,
    include_bia: bool = False,
    include_timeline: bool = False,
    include_glp1: bool = False,
    lang: str = "ru",
) -> dict:
    """Assemble the full Weight dashboard payload in one service call."""
    from vitals.services import body_scan_service, milestones_service
    from vitals.services.analytics import body_metrics

    await refresh_noise_alert(session)
    if include_bia:
        await body_scan_service.refresh_alerts(session)
    await session.commit()

    weights = await list_active_weights(session)
    measurements = await list_body_measurements(session)
    series = await chart_series(
        session,
        include_bia=include_bia,
        include_timeline=include_timeline,
        include_glp1=include_glp1,
    )

    all_weights_result = await session.execute(
        select(WeightLog).order_by(
            WeightLog.date.desc(),
            WeightLog.superseded.asc(),
            WeightLog.id.desc(),
        )
    )
    all_weights = all_weights_result.scalars().all()
    active_source_by_date: dict[date_type, str] = {
        w.date: w.source for w in all_weights if not w.superseded
    }

    bc_scans = await body_scan_service.list_scans(session) if include_bia else []
    bc_latest = bc_scans[0] if bc_scans else None

    body_fat_pct = None
    body_fat_source = None
    if bc_latest:
        bf_val = body_metrics.body_fat_pct_from_scan(bc_latest.metrics)
        if bf_val is not None:
            body_fat_pct = bf_val
            body_fat_source = bc_latest.device or "InBody"

    if body_fat_pct is None:
        for m in measurements:
            if m.body_fat_pct is not None:
                body_fat_pct = m.body_fat_pct
                body_fat_source = "Navy"
                break

    latest_kg = weights[-1].weight_kg if weights else None
    latest_date = weights[-1].date if weights else None
    average7 = series["trend_ma"][-1]["weight_kg"] if series.get("trend_ma") else None
    week_delta = series.get("weekly_delta")

    drug_name = "GLP-1"
    if include_glp1:
        phases_raw = series.get("phases") or []
        if phases_raw and phases_raw[-1].get("drug"):
            drug_name = phases_raw[-1]["drug"]
        else:
            from vitals.services import glp1_service

            last_inj = await glp1_service.last_injection(session)
            if last_inj and last_inj.drug:
                drug_name = last_inj.drug

    weighings = [
        {"date": date_type.fromisoformat(p["date"]), "kg": p["weight_kg"]}
        for p in series.get("raw", [])
    ]
    trend = [
        {"date": date_type.fromisoformat(p["date"]), "kg": p["weight_kg"]}
        for p in series.get("trend_ma", [])
    ]
    dose_phases = [
        {
            "from_date": date_type.fromisoformat(p["start"]),
            "to_date": date_type.fromisoformat(p["end"]) if p.get("end") else None,
            "drug": p.get("drug") or "",
            "dose_mg": float(p.get("dose_mg") or 0.0),
        }
        for p in series.get("phases", [])
    ]

    history = [
        {
            "id": w.id,
            "date": w.date,
            "time": "",
            "weight_kg": w.weight_kg,
            "source": _norm_source(w.source),
            "superseded": bool(w.superseded),
            "superseded_by": (
                _superseded_by_source(active_source_by_date.get(w.date))
                if w.superseded
                else None
            ),
            "note": w.note,
        }
        for w in all_weights
    ]

    trend_info = series.get("trend")
    per_week_kg = trend_info.get("slope_per_week") if trend_info else None

    dose_pace = None
    if include_glp1 and dose_phases:
        active_phase = dose_phases[-1]
        today = today_local()
        days_on_dose = max(0, (today - active_phase["from_date"]).days)
        delta_kg = await dose_phase_delta(session, active_phase, weights=weights)
        drug_val = active_phase.get("drug") or ""
        dose_val = float(active_phase.get("dose_mg") or 0.0)
        dose_pace = {
            "drug": drug_val,
            "dose_mg": dose_val,
            "since_date": active_phase["from_date"],
            "days": days_on_dose,
            "delta_kg": delta_kg,
        }

    # The goal is the active weight milestone — the one Today's goal card shows —
    # and the distance to it is read off the same weekly trend printed above.
    goal_pace = None
    target_kg = await milestones_service.active_weight_target_kg(session)
    if target_kg is not None:
        goal_pace = {
            "target_kg": target_kg,
            "weeks": weeks_to_goal(latest_kg, target_kg, per_week_kg),
        }

    pace = {"per_week_kg": per_week_kg, "dose": dose_pace, "goal": goal_pace}

    last_scan = None
    if bc_latest:
        by_key = {m.metric_key: m for m in bc_latest.metrics if m.metric_key}
        scan_rows = []
        for key in body_metrics.HEADLINE_KEYS:
            m = by_key.get(key)
            if m is not None:
                scan_rows.append(
                    {
                        "label": body_metrics.display_name(key, lang) or m.label,
                        "value": m.value,
                        "unit": body_metrics.display_unit(key, lang),
                    }
                )
        last_scan = {
            "device": bc_latest.device,
            "date": bc_latest.date,
            "rows": scan_rows,
        }

    return {
        "latest_kg": latest_kg,
        "latest_date": latest_date,
        "average7": average7,
        "week_delta_kg": week_delta,
        "body_fat_pct": body_fat_pct,
        "body_fat_source": body_fat_source,
        "drug": drug_name,
        "weighings": weighings,
        "trend": trend,
        "dose_phases": dose_phases,
        "history": history,
        "pace": pace,
        "last_scan": last_scan,
    }


async def collect_measures(
    session: AsyncSession,
    *,
    include_bia: bool = False,
    include_timeline: bool = False,
    lang: str = "ru",
) -> dict:
    """Assemble the Weight Measurements screen payload in one service call."""
    from vitals.services import body_scan_service
    from vitals.services.analytics import body_metrics

    cfg = load_config()
    weights = await list_active_weights(session)
    measurements = await list_body_measurements(session)
    noise_markers = await list_noise_markers(session)
    photos = await list_progress_photos(session)
    series = await chart_series(
        session, include_bia=include_bia, include_timeline=include_timeline
    )

    bc_scans = await body_scan_service.list_scans(session) if include_bia else []
    bc_latest = bc_scans[0] if bc_scans else None

    unified: list[dict] = []
    for m in measurements:
        unified.append(
            {
                "id": m.id,
                "date": m.date,
                "neck_cm": m.neck_cm,
                "waist_cm": m.waist_cm,
                "hips_cm": m.hips_cm,
                "body_fat_pct": m.body_fat_pct,
                "lbm_kg": m.lbm_kg,
                "source": "navy",
                "source_label": "Navy",
                "note": m.note,
            }
        )
    if include_bia:
        for s in bc_scans:
            bf_val = body_metrics.body_fat_pct_from_scan(s.metrics)
            lbm_val = body_metrics.lbm_from_scan(s.metrics)
            if bf_val is not None or lbm_val is not None:
                unified.append(
                    {
                        "id": s.id,
                        "date": s.date,
                        "neck_cm": None,
                        "waist_cm": None,
                        "hips_cm": None,
                        "body_fat_pct": bf_val,
                        "lbm_kg": lbm_val,
                        "source": "scan",
                        "source_label": s.device or "InBody",
                        "note": s.note,
                    }
                )
    sorted_unified = sorted(unified, key=lambda x: x["date"], reverse=True)

    with_bf = [m for m in sorted_unified if m["body_fat_pct"] is not None]
    latest_bf_row = next(
        (m for m in with_bf if m["source"] == "scan"), next(iter(with_bf), None)
    )
    latest_bf = latest_bf_row["body_fat_pct"] if latest_bf_row else None
    latest_bf_source = latest_bf_row["source_label"] if latest_bf_row else None

    headline_metrics: list[dict] = []
    if bc_latest:
        by_key = {m.metric_key: m for m in bc_latest.metrics if m.metric_key}
        for key in body_metrics.HEADLINE_KEYS:
            m = by_key.get(key)
            if m is not None:
                headline_metrics.append(
                    {
                        "label": body_metrics.display_name(key, lang) or m.label,
                        "value": m.value,
                        "unit": body_metrics.display_unit(key, lang),
                    }
                )

    scans_out = [
        {
            "id": s.id,
            "date": s.date,
            "device": s.device,
            "file_key": s.file_key,
            "note": s.note,
            "metrics_count": len(s.metrics),
            "metrics": [
                {
                    "id": m.id,
                    "metric_key": m.metric_key,
                    "label": m.label,
                    "value": m.value,
                    "unit": body_metrics.display_unit(m.metric_key, lang, m.unit),
                    "ref_low": m.ref_low,
                    "ref_high": m.ref_high,
                    "segment": m.segment,
                    "category": m.category,
                }
                for m in s.metrics
            ],
        }
        for s in bc_scans
    ]

    photos_out = [
        {
            "id": p.id,
            "date": p.date,
            "file_key": p.file_key,
            "url": f"/static/{p.file_key}",
            "note": p.note,
        }
        for p in photos
    ]

    noise_out = [
        {
            "id": n.id,
            "start_date": n.start_date,
            "end_date": n.end_date,
            "reason": n.reason,
            "direction": n.direction,
        }
        for n in noise_markers
    ]

    latest_kg = weights[-1].weight_kg if weights else None
    average7 = series["trend_ma"][-1]["weight_kg"] if series.get("trend_ma") else None

    return {
        "latest_kg": latest_kg,
        "average7": average7,
        "body_fat_pct": latest_bf,
        "body_fat_source": latest_bf_source,
        "week_delta_kg": series.get("weekly_delta"),
        "height_cm": cfg.height_cm,
        "sex": cfg.sex,
        "body_comp_enabled": include_bia,
        "llm_configured": bool(cfg.openrouter_api_key),
        "headline_metrics": headline_metrics,
        "measurements": sorted_unified,
        "scans": scans_out,
        "photos": photos_out,
        "noise_markers": noise_out,
    }

