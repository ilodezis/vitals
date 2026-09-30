"""``/api/v1/hrt`` — HRT/TRT protocol dashboard and mutations."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.enums import CycleKind, DoseUnit
from vitals.services import (
    hrt_cycle_service,
    hrt_service,
    hrt_template_service,
)
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.hrt import (
    HrtCycleClose,
    HrtCycleCreate,
    HrtCycleCreated,
    HrtCycleItemCreate,
    HrtCycleItemCreated,
    HrtCycleItemPatch,
    HrtDoseCreate,
    HrtDoseCreated,
    HrtDosePatch,
    HrtReleaseResponse,
    HrtSideEffectCreate,
    HrtSideEffectCreated,
    HrtTemplateCreateCycle,
    HrtTemplateImport,
    HrtTemplateSave,
    HrtView,
)
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/hrt", dependencies=[Depends(require_auth)])


@router.get("", response_model=HrtView)
async def read_hrt(db: AsyncSession = Depends(get_session)) -> HrtView:
    """The whole HRT/TRT screen in one request: active course, position in cycle,
    dose journal, body-map injection rotation, side effects, and cycle templates.
    ONLY RECORDING, NO DOSE RECOMMENDATIONS."""
    data = await hrt_service.collect(db)
    return HrtView.model_validate(
        {
            **data,
            "units": [u.value for u in DoseUnit],
            "cycleKinds": [k.value for k in CycleKind],
        }
    )


@router.get("/release", response_model=HrtReleaseResponse)
async def read_hrt_release(
    days_back: int = 30,
    days_forward: int = 60,
    db: AsyncSession = Depends(get_session),
) -> HrtReleaseResponse:
    """Estimated active compound release curve over a sliding time window."""
    today = today_local()
    series = await hrt_cycle_service.release_series(
        db,
        start=today - timedelta(days=days_back),
        end=today + timedelta(days=days_forward),
    )
    return HrtReleaseResponse(series=series, today=today.isoformat())


# ── Doses ─────────────────────────────────────────────────────────────────────
@router.post(
    "/doses",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtDoseCreated,
    responses=MUTATION_ERRORS,
)
async def create_hrt_dose(
    body: HrtDoseCreate, db: AsyncSession = Depends(get_session)
) -> HrtDoseCreated:
    """Record an administration of a compound."""
    row = await hrt_service.log_dose(
        db,
        compound_key=body.compound_key,
        on_date=body.date,
        dose=body.dose,
        unit=body.unit,
        volume_ml=body.volume_ml,
        concentration_mg_ml=body.concentration_mg_ml,
        brand=body.brand,
        lab=body.lab,
        batch=body.batch,
        site=body.site,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return HrtDoseCreated(id=row.id)


@router.patch(
    "/doses/{dose_id}",
    response_model=HrtDoseCreated,
    responses=MUTATION_ERRORS,
)
async def update_hrt_dose(
    dose_id: int, body: HrtDosePatch, db: AsyncSession = Depends(get_session)
) -> HrtDoseCreated:
    """Update a previously logged dose."""
    existing = await db.get(hrt_service.HrtDose, dose_id)
    if existing is None:
        return not_found()
    row = await hrt_service.update_dose(
        db,
        dose_id,
        compound_key=body.compound_key or existing.compound_key,
        on_date=body.date or existing.date,
        dose=body.dose if body.dose is not None else existing.dose,
        unit=body.unit or existing.unit,
        volume_ml=body.volume_ml if "volume_ml" in body.model_fields_set else existing.volume_ml,
        concentration_mg_ml=(
            body.concentration_mg_ml
            if "concentration_mg_ml" in body.model_fields_set
            else existing.concentration_mg_ml
        ),
        brand=body.brand if "brand" in body.model_fields_set else existing.brand,
        lab=body.lab if "lab" in body.model_fields_set else existing.lab,
        batch=body.batch if "batch" in body.model_fields_set else existing.batch,
        site=body.site if "site" in body.model_fields_set else existing.site,
        note=body.note if "note" in body.model_fields_set else existing.note,
        override=body.override,
    )
    if row is None:
        return not_found()
    await db.commit()
    return HrtDoseCreated(id=row.id)


@router.delete("/doses/{dose_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hrt_dose(dose_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a logged dose."""
    if not await hrt_service.delete_dose(db, dose_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Cycles ────────────────────────────────────────────────────────────────────
@router.post(
    "/cycles",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtCycleCreated,
    responses=MUTATION_ERRORS,
)
async def create_hrt_cycle(
    body: HrtCycleCreate, db: AsyncSession = Depends(get_session)
) -> HrtCycleCreated:
    """Start a new HRT/TRT cycle."""
    row = await hrt_cycle_service.add_cycle(
        db,
        kind=body.kind,
        start_date=body.start_date,
        name=body.name,
        end_date=body.end_date,
        note=body.note,
    )
    await db.commit()
    return HrtCycleCreated(id=row.id)


@router.post(
    "/cycles/{cycle_id}/close",
    response_model=HrtCycleCreated,
    responses=MUTATION_ERRORS,
)
async def close_hrt_cycle(
    cycle_id: int,
    body: HrtCycleClose,
    db: AsyncSession = Depends(get_session),
) -> HrtCycleCreated:
    """Close an active HRT/TRT cycle."""
    end = body.end_date or today_local()
    row = await hrt_cycle_service.close_cycle(db, cycle_id, end_date=end)
    if row is None:
        return not_found()
    await db.commit()
    return HrtCycleCreated(id=row.id)


@router.delete("/cycles/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hrt_cycle(cycle_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a cycle and its planned items."""
    if not await hrt_cycle_service.delete_cycle(db, cycle_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Cycle items ───────────────────────────────────────────────────────────────
@router.post(
    "/cycles/{cycle_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtCycleItemCreated,
    responses=MUTATION_ERRORS,
)
async def create_hrt_cycle_item(
    cycle_id: int,
    body: HrtCycleItemCreate,
    db: AsyncSession = Depends(get_session),
) -> HrtCycleItemCreated:
    """Add a planned compound administration segment to a cycle."""
    segment: dict[str, Any] = {"dose": body.dose, "interval_days": body.interval_days}
    if body.duration_days:
        segment["duration_days"] = body.duration_days

    week = body.start_week
    if week is not None and (week < 1 or week != int(week)):
        raise ValueError("start_week must be a whole number >= 1")
    offset_days = int((week - 1) * 7) if week else 0

    row = await hrt_cycle_service.add_cycle_item(
        db,
        cycle_id,
        compound_key=body.compound_key,
        schedule=[segment],
        unit=body.unit,
        start_offset_days=offset_days,
        note=body.note,
    )
    await db.commit()
    return HrtCycleItemCreated(id=row.id)


@router.patch(
    "/cycle-items/{item_id}",
    response_model=HrtCycleItemCreated,
    responses=MUTATION_ERRORS,
)
async def update_hrt_cycle_item(
    item_id: int,
    body: HrtCycleItemPatch,
    db: AsyncSession = Depends(get_session),
) -> HrtCycleItemCreated:
    """Update a planned cycle compound."""
    week = body.start_week
    if week is not None and (week < 1 or week != int(week)):
        raise ValueError("start_week must be a whole number >= 1")
    offset = int((week - 1) * 7) if week is not None else None

    schedule = None
    if body.dose is not None and body.interval_days is not None:
        seg: dict[str, Any] = {"dose": body.dose, "interval_days": body.interval_days}
        if body.duration_days:
            seg["duration_days"] = body.duration_days
        schedule = [seg]

    row = await hrt_cycle_service.update_cycle_item(
        db, item_id, schedule=schedule, start_offset_days=offset
    )
    if row is None:
        return not_found()
    await db.commit()
    return HrtCycleItemCreated(id=row.id)


@router.delete("/cycle-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hrt_cycle_item(item_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a planned cycle item."""
    if not await hrt_cycle_service.delete_cycle_item(db, item_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Templates ─────────────────────────────────────────────────────────────────
@router.post(
    "/cycles/{cycle_id}/save-template",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtCycleCreated,
    responses=MUTATION_ERRORS,
)
async def save_hrt_cycle_template(
    cycle_id: int,
    body: HrtTemplateSave,
    db: AsyncSession = Depends(get_session),
) -> HrtCycleCreated:
    """Save an existing cycle as a reusable template."""
    row = await hrt_template_service.save_cycle_as_template(db, cycle_id, name=body.name)
    await db.commit()
    return HrtCycleCreated(id=row.id)


@router.post(
    "/templates/{template_id}/create-cycle",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtCycleCreated,
    responses=MUTATION_ERRORS,
)
async def create_cycle_from_hrt_template(
    template_id: int,
    body: HrtTemplateCreateCycle,
    db: AsyncSession = Depends(get_session),
) -> HrtCycleCreated:
    """Instantiate a new cycle from a template."""
    row = await hrt_template_service.create_cycle_from_template(
        db, template_id, start_date=body.start_date, name=body.name
    )
    await db.commit()
    return HrtCycleCreated(id=row.id)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hrt_template(template_id: int, db: AsyncSession = Depends(get_session)):
    """Delete a cycle template."""
    if not await hrt_template_service.delete_template(db, template_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/templates/{template_id}/export")
async def export_hrt_template(
    template_id: int, db: AsyncSession = Depends(get_session)
):
    """Export a template as a portable JSON payload."""
    template = await hrt_template_service.get_template(db, template_id)
    if template is None:
        return not_found()
    payload = hrt_template_service.export_template(template)
    return JSONResponse(content=payload)


@router.post(
    "/templates/import",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtCycleCreated,
    responses=MUTATION_ERRORS,
)
async def import_hrt_template(
    body: HrtTemplateImport, db: AsyncSession = Depends(get_session)
) -> HrtCycleCreated:
    """Import a shared cycle template JSON payload."""
    row = await hrt_template_service.import_template(db, body.payload)
    await db.commit()
    return HrtCycleCreated(id=row.id)


# ── Side effects ──────────────────────────────────────────────────────────────
@router.post(
    "/side-effects",
    status_code=status.HTTP_201_CREATED,
    response_model=HrtSideEffectCreated,
    responses=MUTATION_ERRORS,
)
async def create_hrt_side_effect(
    body: HrtSideEffectCreate, db: AsyncSession = Depends(get_session)
) -> HrtSideEffectCreated:
    """Record an adverse effect / symptom."""
    row = await hrt_service.log_side_effect(
        db,
        on_date=body.date,
        effect_type=body.effect_type,
        severity=body.severity,
        note=body.note,
    )
    await db.commit()
    return HrtSideEffectCreated(id=row.id)


@router.delete("/side-effects/{effect_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hrt_side_effect(
    effect_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a recorded side effect."""
    if not await hrt_service.delete_side_effect(db, effect_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
