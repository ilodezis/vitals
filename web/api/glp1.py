"""``/api/v1/glp1`` — GLP-1 protocol dashboard and mutations."""
from __future__ import annotations

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import glp1_service
from vitals.utils.timeutils import today_local
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.glp1 import (
    Glp1CycleCreate,
    Glp1CycleResponse,
    Glp1InjectionCreate,
    Glp1InjectionCreated,
    Glp1SideEffectCreate,
    Glp1SideEffectCreated,
    Glp1View,
)
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/glp1", dependencies=[Depends(require_auth)])


@router.get("", response_model=Glp1View)
async def read_glp1(db: AsyncSession = Depends(get_session)) -> Glp1View:
    """The whole GLP-1 screen in one request: current dose hero, cycle progression,
    dose & weight trend, body-map injection site usage, side effects, and history."""
    await glp1_service.refresh_plateau_alert(db)
    await db.commit()
    data = await glp1_service.collect(db)
    return Glp1View.model_validate(data)


@router.post(
    "/injections",
    status_code=status.HTTP_201_CREATED,
    response_model=Glp1InjectionCreated,
    responses=MUTATION_ERRORS,
)
async def create_glp1_injection(
    body: Glp1InjectionCreate, db: AsyncSession = Depends(get_session)
) -> Glp1InjectionCreated:
    """Log a GLP-1 injection shot."""
    drug = body.drug
    if not drug:
        active = await glp1_service.active_dose_phase(db)
        if active:
            drug = active.drug
        else:
            last = await glp1_service.last_injection(db)
            drug = last.drug if last else "Семаглутид"

    row = await glp1_service.log_injection(
        db,
        on_date=body.date,
        drug=drug,
        dose_mg=body.dose_mg,
        site=body.site,
        note=body.note,
        override=body.override,
    )
    await db.commit()
    return Glp1InjectionCreated(id=row.id)


@router.delete("/injections/{injection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glp1_injection(
    injection_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a recorded injection shot."""
    if not await glp1_service.delete_injection(db, injection_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/cycles",
    status_code=status.HTTP_201_CREATED,
    response_model=Glp1CycleResponse,
    responses=MUTATION_ERRORS,
)
async def create_or_close_glp1_cycle(
    body: Glp1CycleCreate, db: AsyncSession = Depends(get_session)
) -> Glp1CycleResponse:
    """Create a new dose phase (cycle) or close an ongoing one."""
    if body.action == "close":
        today = today_local()
        end_date = body.end_date or today
        if body.cycle_id:
            phase = await db.get(glp1_service.DosePhase, body.cycle_id)
        else:
            phase = await glp1_service.active_dose_phase(db)
        if phase is None:
            return not_found()
        phase.end_date = end_date
        await db.commit()
        return Glp1CycleResponse(id=phase.id, ok=True)

    if not body.start_date:
        raise ValueError("start_date is required")
    if not body.drug:
        raise ValueError("drug is required")
    if body.dose_mg is None or body.dose_mg <= 0:
        raise ValueError("dose_mg must be a positive number")

    row = await glp1_service.add_dose_phase(
        db,
        start_date=body.start_date,
        drug=body.drug,
        dose_mg=body.dose_mg,
        end_date=body.end_date,
        note=body.note,
    )
    await db.commit()
    return Glp1CycleResponse(id=row.id, ok=True)


@router.post(
    "/side-effects",
    status_code=status.HTTP_201_CREATED,
    response_model=Glp1SideEffectCreated,
    responses=MUTATION_ERRORS,
)
async def create_glp1_side_effect(
    body: Glp1SideEffectCreate, db: AsyncSession = Depends(get_session)
) -> Glp1SideEffectCreated:
    """Record a side effect symptom with 1-5 severity."""
    row = await glp1_service.log_side_effect(
        db,
        on_date=body.date,
        effect_type=body.effect_type,
        severity=body.severity,
        note=body.note,
    )
    await db.commit()
    return Glp1SideEffectCreated(id=row.id)


@router.delete("/side-effects/{effect_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glp1_side_effect(
    effect_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a recorded side effect."""
    if not await glp1_service.delete_side_effect(db, effect_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
