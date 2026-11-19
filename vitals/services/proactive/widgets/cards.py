"""Building and sending the cards (the handler only reacts to taps)."""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.services import weight_service
from vitals.services.proactive import delivery
from vitals.services.proactive.channels import Notifier, WidgetNotifier, WidgetSpec
from vitals.services.proactive.widgets import state
from vitals.utils.timeutils import today_local

logger = logging.getLogger(__name__)


def weight_dedupe_key(on_date: date_type) -> str:
    return f"weight:{on_date.isoformat()}"


async def weight_card_state(session: AsyncSession, today: date_type, *, error: str = "") -> str:
    """The weight card's chat state: the last week, and today's reading if any."""
    weights = await weight_service.list_active_weights(
        session, start=today - timedelta(days=6), end=today
    )
    series = state.weight_series(weights, today)
    active = await weight_service.get_active_weight(session, today)
    logged = round(active.weight_kg * 10) if active is not None else 0
    return state.weight_state(today, series, logged=logged, error=error)


async def send_weight_card(
    session: AsyncSession, notifier: Optional[Notifier], *, now: Optional[datetime] = None
) -> Optional[object]:
    """Offer the weight card once a day, only while today's weight is missing.

    Widget-only: there is no text twin (a number can't be typed into a button), so
    when the flag is off or the widget is refused, nothing is sent and the owner
    logs in the app as before. Never raises — it rides after the brief.
    """
    if notifier is None or not load_config().telegram_widgets:
        return None
    if not isinstance(notifier, WidgetNotifier):
        return None
    try:
        today = now.date() if now is not None else today_local()
        if await weight_service.get_active_weight(session, today) is not None:
            return None
        spec = WidgetSpec(
            kind=state.KIND_WEIGHT,
            html=state.template(state.KIND_WEIGHT),
            chat_data=await weight_card_state(session, today),
        )
        return await delivery.send(
            session,
            notifier,
            text=f"⚖️ Вес · {today:%d.%m}",
            category=delivery.CATEGORY_WEIGHT,
            dedupe_key=weight_dedupe_key(today),
            widget=spec,
            widget_only=True,
            now=now,
        )
    except Exception:
        logger.warning("weight card not sent", exc_info=True)
        return None
