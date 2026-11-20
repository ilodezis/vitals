"""Шов 1 — the delivery channel, behind one small protocol.

``Notifier`` is the whole contract: send some text, optionally with tap-buttons,
optionally as a reply to an earlier message; get back the channel's own id for
what was sent (so a later reply can be matched to it) — plus redraw one already
sent. Nothing above this module imports ``httpx``, knows a chat id, or has heard
of Telegram.

    Adding web push / email / anything else: a class with these three methods
    plus one line in :func:`build_notifier`. No caller changes.

``answer_callback`` and ``edit`` are in the protocol on purpose even though only
Telegram has the concept: acknowledging a tap and redrawing a message are
*channel* details, and a channel without taps implements them as no-ops. The
alternative — callers sniffing for the method with ``getattr`` — would leak "is
this Telegram?" back up the stack.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable

from vitals.config import Config, load_config

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
_TIMEOUT_SECONDS = 15.0
# Bot API hard limit. Over it the send is rejected outright, so a brief whose LLM
# tail ran long would simply never arrive — truncating visibly beats silence.
_MAX_TEXT = 4096

# One button = (visible label, callback payload). A flat list renders one button
# per row, which is all the current messages need; grouping into rows can be
# added the day a message actually wants it.
Buttons = Sequence[tuple[str, str]]


# Caption limit for a media message (the widget's caption is what the chat list,
# notifications and clients without widget support show).
_MAX_CAPTION = 1024


@dataclass(frozen=True)
class WidgetSpec:
    """A widget to send instead of plain text: static HTML plus its first state.

    ``kind`` names the template (stored in the journal so a later redraw knows the
    message is a widget). ``chat_data`` is the only part that ever changes.

    ``caption`` is the text under the card (``None`` = the message's plain text).
    ``keyboard`` carries the message's inline buttons under the card as well.
    ``queries`` lets the card ask the bot anything at all: a card that only shows
    numbers is sent without it, so there is no request path to guard."""

    kind: str
    html: str
    chat_data: str
    width: int = 0
    height: int = 0
    caption: Optional[str] = None
    keyboard: bool = False
    queries: bool = True


@runtime_checkable
class WidgetNotifier(Protocol):
    """Optional second face of a channel: widget messages. Kept apart from
    :class:`Notifier` so channels (and test fakes) without widgets stay valid."""

    async def send_widget(
        self, caption: str, widget: WidgetSpec, *, buttons: Optional[Buttons] = None
    ) -> str:
        """Send ``widget``; return the message id. Raises when refused."""

    async def edit_widget_data(self, message_id: str, chat_data: str) -> None:
        """Replace a sent widget's chat state. A no-change edit is not an error."""

    async def edit_buttons(self, message_id: str, buttons: Optional[Buttons]) -> None:
        """Replace (or, with none, remove) the inline buttons under a message."""

    async def answer_widget_query(self, query_id: str, data: str = "") -> None:
        """Answer a widget request (must happen within 15 s of the tap)."""


def _clip(text: str) -> str:
    if len(text) > _MAX_TEXT:
        logger.warning("message of %s chars truncated to %s", len(text), _MAX_TEXT)
        return text[: _MAX_TEXT - 1] + "…"
    return text


def _keyboard(buttons: Optional[Buttons]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data}] for label, data in buttons or ()
        ]
    }


@runtime_checkable
class Notifier(Protocol):
    channel: str

    async def send(
        self,
        text: str,
        *,
        buttons: Optional[Buttons] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Deliver ``text``; return the channel's id for the sent message."""

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Acknowledge a button tap (no-op on channels without buttons)."""

    async def edit(
        self,
        message_id: str,
        text: str,
        *,
        buttons: Optional[Buttons] = None,
    ) -> None:
        """Redraw an already-sent message (no-op where the channel can't)."""


class TelegramNotifier:
    """Bot API over plain ``httpx``. One chat, passed in — not read from config
    here, so the class itself carries nothing single-user about it."""

    channel = "telegram"

    def __init__(self, token: str, chat_id: str, *, base_url: str = TELEGRAM_API):
        self._token = token
        self._chat_id = chat_id
        self._base_url = base_url.rstrip("/")

    async def _call(self, method: str, payload: dict) -> dict:
        import httpx  # already a dependency; imported here like the other clients

        url = f"{self._base_url}/bot{self._token}/{method}"
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("ok"):
            raise RuntimeError(
                f"Telegram {method} failed ({resp.status_code}): "
                f"{data.get('description') or resp.text[:200]}"
            )
        return data.get("result") or {}

    async def send(
        self,
        text: str,
        *,
        buttons: Optional[Buttons] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        # No parse_mode: everything sent so far is plain prose, and Markdown/HTML
        # would turn an unescaped '_' or '*' in the owner's own words into a
        # failed send. Formatting can be switched on when a message wants it.
        payload: dict = {"chat_id": self._chat_id, "text": _clip(text)}
        if buttons:
            payload["reply_markup"] = _keyboard(buttons)
        if reply_to:
            payload["reply_to_message_id"] = int(reply_to)
            # The message may have been deleted; a reply that can't attach should
            # still arrive rather than erroring the whole send.
            payload["allow_sending_without_reply"] = True
        result = await self._call("sendMessage", payload)
        return str(result.get("message_id") or "")

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._call(
            "answerCallbackQuery", {"callback_query_id": callback_id, "text": text}
        )

    async def edit(
        self,
        message_id: str,
        text: str,
        *,
        buttons: Optional[Buttons] = None,
    ) -> None:
        # ``reply_markup`` always rides along, empty included: left out entirely,
        # Telegram keeps the previous keyboard — so the question just answered
        # would stay tappable under a line that already says it was answered.
        await self._call(
            "editMessageText",
            {
                "chat_id": self._chat_id,
                "message_id": int(message_id),
                "text": _clip(text),
                "reply_markup": _keyboard(buttons),
            },
        )


    # ── Widgets (Bot API 10.4) ──────────────────────────────────────────────────
    async def send_widget(
        self, caption: str, widget: WidgetSpec, *, buttons: Optional[Buttons] = None
    ) -> str:
        payload: dict = {
            "chat_id": self._chat_id,
            "html": widget.html,
            "chat_data": widget.chat_data,
            # Widget code and state live on Telegram's servers; never forwardable.
            "protect_content": True,
        }
        if caption:
            payload["caption"] = (
                caption[: _MAX_CAPTION - 1] + "…" if len(caption) > _MAX_CAPTION else caption
            )
        if widget.queries:
            payload["allow_queries"] = True
        if buttons:
            payload["reply_markup"] = _keyboard(buttons)
        if widget.width:
            payload["width"] = widget.width
        if widget.height:
            payload["height"] = widget.height
        result = await self._call("sendWidget", payload)
        return str(result.get("message_id") or "")

    async def edit_widget_data(self, message_id: str, chat_data: str) -> None:
        try:
            await self._call(
                "editMessageWidgetData",
                {
                    "chat_id": self._chat_id,
                    "message_id": int(message_id),
                    "chat_data": chat_data,
                },
            )
        except RuntimeError as exc:
            # Same state twice: nothing to redraw, which is the goal state.
            if "not modified" in str(exc).lower():
                return
            raise

    async def edit_buttons(self, message_id: str, buttons: Optional[Buttons]) -> None:
        try:
            await self._call(
                "editMessageReplyMarkup",
                {
                    "chat_id": self._chat_id,
                    "message_id": int(message_id),
                    "reply_markup": _keyboard(buttons),
                },
            )
        except RuntimeError as exc:
            if "not modified" in str(exc).lower():
                return
            raise

    async def answer_widget_query(self, query_id: str, data: str = "") -> None:
        payload: dict = {"widget_query_id": query_id}
        if data:
            payload["data"] = data
        await self._call("answerWidgetQuery", payload)


def build_notifier(config: Optional[Config] = None) -> Optional[Notifier]:
    """The factory. ``None`` = no channel configured — callers treat that
    as "stay quiet", which is how the app behaves before the bot exists."""
    config = config or load_config()
    if config.telegram_bot_token and config.telegram_chat_id:
        return TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    logger.debug("no delivery channel configured; proactive messages are dropped")
    return None
