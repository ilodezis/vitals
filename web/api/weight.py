"""``/api/v1/weight`` — logging, correcting and taking back a weight.

The same service calls as the form on ``/weight/log``. The conflict engine's block
and the service's range check reach the client as 409 and 400 through the route
class (``web.api.errors``), so nothing here catches them.
"""
from __future__ import annotations

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import weight_service
from web.api.errors import MUTATION_ERRORS, ApiRouter, not_found
from web.api.schemas.weight import WeightLogCreate, WeightLogCreated, WeightLogPatch, WeightLogRef
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/weight", dependencies=[Depends(require_auth)])


@router.post(
    "/logs",
    status_code=status.HTTP_201_CREATED,
    response_model=WeightLogCreated,
    responses=MUTATION_ERRORS,
)
async def create_weight_log(
    body: WeightLogCreate, db: AsyncSession = Depends(get_session)
) -> WeightLogCreated:
    """Log a weight as a manual reading. A reading the day already holds comes back
    with ``created: false``; a block rule answers 409 until ``override`` is set."""
    before = await weight_service.get_active_weight(db, body.date)
    row = await weight_service.log_weight(
        db, on_date=body.date, weight_kg=body.weight_kg, note=body.note, override=body.override
    )
    await db.commit()
    return WeightLogCreated(id=row.id, created=before is None or before.id != row.id)


@router.patch("/logs/{log_id}", response_model=WeightLogRef, responses=MUTATION_ERRORS)
async def update_weight_log(
    log_id: int, body: WeightLogPatch, db: AsyncSession = Depends(get_session)
):
    """Correct a reading; whatever the body leaves out stays as it was."""
    row = await weight_service.get_weight_log(db, log_id)
    if row is None:
        return not_found()
    updated = await weight_service.update_weight_log(
        db,
        log_id,
        on_date=body.date if body.date is not None else row.date,
        weight_kg=body.weight_kg if body.weight_kg is not None else row.weight_kg,
        note=body.note if "note" in body.model_fields_set else row.note,
        override=body.override,
    )
    if updated is None:
        return not_found()
    await db.commit()
    return WeightLogRef(id=updated.id)


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_weight_log(log_id: int, db: AsyncSession = Depends(get_session)):
    """Take a reading back. If it was the day's active one, the reading it had
    outranked (a Garmin import) becomes active again."""
    if not await weight_service.delete_weight_log(db, log_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
