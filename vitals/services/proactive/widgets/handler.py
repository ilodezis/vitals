"""``widget_query`` updates: a tap inside a widget, arriving as a request.

The path in, in the order it is checked:

1. **Who.** The update must come from the owner — both the tapping user and the
   private chat equal ``VITALS_TELEGRAM_CHAT_ID`` — or it is dropped with a log
   line and no answer. (The webhook already discards other chats before this runs;
   the check is repeated here because this module is the one that acts on the
   request.) Requests with no chat (inline or forwarded copies) never match.
2. **Switches.** Widgets flag off, or the proactive bot switched off: refuse.
3. **What.** ``payload.parse`` against the closed action list. Unknown → refuse.
4. **Which message.** The journal row of the message the tap came from decides the
   day, the slot and the kind of card. The payload never names a date.
5. **Do it, without override.** The services are called with ``override=False``: a
   blocking conflict comes back to the widget as an error line. Override stays a
   web-app action.

Every request is answered (the widget's promise would otherwise end in a timeout),
with the card's new state as the answer, and the same state is then written to the
message so a second device shows it too. Replays are harmless: the ticks carry the
wanted state (not a toggle), and Telegram's own
retries are dropped upstream by ``update_id``.
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import load_config
from vitals.enums import Source
from vitals.services import modules_service, skincare_service
from vitals.services.conflict_engine import ConflictBlocked
from vitals.services.proactive import delivery, prefs
from vitals.services.proactive.channels import Notifier, WidgetNotifier
from vitals.services.proactive.widgets import payload, state

logger = logging.getLogger(__name__)

_QUERY_ID_MAX = 40


def is_owner_query(wq: dict, owner_chat_id: str) -> bool:
    """True only for a request from the owner, in their private chat."""
    if not owner_chat_id:
        return False
    sender = wq.get("from")
    chat = wq.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return False
    if chat.get("type") != "private":
        return False
    sender_id, chat_id = sender.get("id"), chat.get("id")
    if isinstance(sender_id, bool) or isinstance(chat_id, bool):
        return False
    return str(sender_id) == owner_chat_id and str(chat_id) == owner_chat_id


def _message_id(wq: dict) -> Optional[int]:
    value = wq.get("message_id")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


async def _answer(notifier: Optional[Notifier], query_id: str, data: str = "") -> None:
    if not isinstance(notifier, WidgetNotifier):
        return
    try:
        await notifier.answer_widget_query(query_id, data)
    except Exception:
        logger.warning("could not answer widget query %s", query_id, exc_info=True)


async def _push_state(notifier: Optional[Notifier], message_id: int, chat_data: str) -> None:
    """Write the new state to the message itself (other devices, later opens)."""
    if not isinstance(notifier, WidgetNotifier):
        return
    try:
        await notifier.edit_widget_data(str(message_id), chat_data)
    except Exception:
        logger.warning("could not update widget state of message %s", message_id, exc_info=True)


async def handle_widget_query(
    session: AsyncSession, update: dict, *, notifier: Optional[Notifier]
) -> None:
    wq = update.get("widget_query")
    if not isinstance(wq, dict):
        return
    config = load_config()
    if not is_owner_query(wq, config.telegram_chat_id):
        logger.warning("widget query from a non-owner or non-private context dropped")
        return

    query_id = str(wq.get("id") or "")
    if not query_id.isascii() or not query_id.isalnum() or len(query_id) > _QUERY_ID_MAX:
        logger.warning("widget query with a malformed id dropped")
        return

    if not config.telegram_widgets or not await prefs.bot_enabled(session):
        logger.info("widget query refused: widgets or the bot are switched off")
        await _answer(notifier, query_id)
        return

    action = payload.parse(wq.get("data"))
    message_id = _message_id(wq)
    if action is None or message_id is None:
        logger.warning("widget query refused: payload not on the action list")
        await _answer(notifier, query_id)
        return

    row = await delivery.find_sent(session, str(message_id))
    kind = (row.payload or {}).get("widget") if row is not None else None
    chat_data: Optional[str] = None
    if row is not None and kind == state.KIND_SKINCARE and isinstance(
        action, (payload.SkincareTick, payload.SkincareAll)
    ):
        chat_data = await _skincare(session, row.dedupe_key, action)
    else:
        logger.warning("widget query refused: no matching widget message")

    if chat_data is None:
        await _answer(notifier, query_id)
        return
    await _answer(notifier, query_id, chat_data)
    await _push_state(notifier, message_id, chat_data)


def _split_key(dedupe_key: Optional[str], prefix: str, parts: int) -> Optional[list[str]]:
    pieces = (dedupe_key or "").split(":")
    if len(pieces) != parts or pieces[0] != prefix:
        return None
    return pieces


async def _skincare(
    session: AsyncSession,
    dedupe_key: Optional[str],
    action: "payload.SkincareTick | payload.SkincareAll",
) -> Optional[str]:
    pieces = _split_key(dedupe_key, "skincare", 3)
    if pieces is None or not (await modules_service.get_enabled_modules(session)).get("skincare"):
        return None
    try:
        on_date = date_type.fromisoformat(pieces[1])
    except ValueError:
        return None
    slot = pieces[2]
    if slot not in skincare_service.SLOTS:
        return None

    error = ""
    plan_items = (await skincare_service.plan_for(session, on_date))[slot]
    try:
        if isinstance(action, payload.SkincareAll):
            await skincare_service.complete_slot(
                session, on_date=on_date, slot=slot, override=False, source=Source.TELEGRAM.value
            )
        elif any(i["product_id"] == action.product_id for i in plan_items):
            await skincare_service.set_check(
                session,
                on_date=on_date,
                product_id=action.product_id,
                slot=slot,
                done=action.done,
                override=False,
                source=Source.TELEGRAM.value,
            )
        else:
            error = "Нет в списке"
    except ConflictBlocked as blocked:
        # Never overridden from here: the app is where a block is knowingly waived.
        error = f"Конфликт: {blocked}. Отметь в приложении"
    except LookupError:
        error = "Продукт удалён"
    items = (await skincare_service.plan_for(session, on_date))[slot]
    return state.skincare_state(slot, items, error=error)

