"""``/api/v1/signals`` — Signals feed, key frequencies, and cleanup endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services import signals_service
from web.api.errors import ApiRouter, not_found
from web.api.schemas.signals import SignalsView
from web.deps import get_session, require_auth

router = ApiRouter(prefix="/signals", dependencies=[Depends(require_auth)])


@router.get("", response_model=SignalsView)
async def read_signals(
    limit: int = 200,
    db: AsyncSession = Depends(get_session),
) -> SignalsView:
    """The free-text signals feed and key frequencies."""
    data = await signals_service.collect(db, limit=limit)
    return SignalsView.model_validate(data)


@router.delete("/{signal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signal(
    signal_id: int, db: AsyncSession = Depends(get_session)
):
    """Delete a wrongly parsed signal row completely."""
    if not await signals_service.delete_signal(db, signal_id):
        return not_found()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{batch_id}/misparse")
async def mark_signal_misparse(
    batch_id: str, db: AsyncSession = Depends(get_session)
):
    """Mark an entire message batch as 'не то' (misparse)."""
    count = await signals_service.mark_misparse(db, batch_id)
    await db.commit()
    return {"ok": True, "count": count}
