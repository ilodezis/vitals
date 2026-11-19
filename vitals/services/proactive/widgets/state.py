"""What goes to Telegram: the widget templates and the chat state.

Data minimisation is the rule here. The HTML and the state are stored on Telegram's
servers, so a card carries only what it draws: product names and ticks, a week of
weights. No ids of other records, no tokens, no URLs — and no user text is ever
spliced into the HTML: the templates are static and the state is JSON the widget
reads with ``JSON.parse`` and paints with ``textContent``.

State format (UTF-8 JSON, hard cap 1024 bytes — the Bot API limit):

    skincare  {"v":1,"r":rev,"t":title,"i":[[product id,name,0|1],…],"e":error}
    weight    {"v":1,"r":rev,"d":"dd.mm","w":[7 × tenths of kg, 0 = no reading],
               "c":stepper start,"l":logged today (0 = not yet),"e":error}

``r`` is a revision the widget uses to ignore an older state arriving late.
"""
from __future__ import annotations

import json
from datetime import date as date_type, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence

from vitals.services.proactive.channels import WidgetSpec
from vitals.utils.timeutils import now_local

STATE_MAX_BYTES = 1024
_TEMPLATES = Path(__file__).parent / "templates"
_NAME_MAX = 18
_ITEMS_MAX = 8
_ERROR_MAX = 80

KIND_SKINCARE = "skincare"
KIND_WEIGHT = "weight"

SKINCARE_TITLES = {"morning": "☀️ Утренний уход", "evening": "🌙 Вечерний уход"}


@lru_cache(maxsize=None)
def template(kind: str) -> str:
    """The static HTML of one widget. Read once; never modified at send time."""
    return (_TEMPLATES / f"{kind}.html").read_text(encoding="utf-8")


def revision() -> int:
    return int(now_local().timestamp())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _encode(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def _fit(state: dict[str, Any], list_key: Optional[str] = None) -> str:
    """Serialise, dropping list items from the tail until it fits the cap."""
    text = _encode(state)
    while len(text.encode("utf-8")) > STATE_MAX_BYTES and list_key and state[list_key]:
        state[list_key] = state[list_key][:-1]
        text = _encode(state)
    if len(text.encode("utf-8")) > STATE_MAX_BYTES:
        text = _encode({"v": 1, "r": state.get("r", 0), "e": "too large"})
    return text


def skincare_state(slot: str, items: Sequence[dict], *, error: str = "") -> str:
    rows = [
        [i["product_id"], _clip(str(i["name"]), _NAME_MAX), 1 if i["done"] else 0]
        for i in items
        if i.get("product_id") is not None
    ][:_ITEMS_MAX]
    state: dict[str, Any] = {
        "v": 1,
        "r": revision(),
        "t": SKINCARE_TITLES.get(slot, ""),
        "i": rows,
    }
    if error:
        state["e"] = _clip(error, _ERROR_MAX)
    return _fit(state, "i")


def weight_series(weights: Sequence[Any], today: date_type, days: int = 7) -> list[int]:
    """Last ``days`` days ending today, tenths of kg; 0 where nothing was weighed."""
    by_date = {w.date: w.weight_kg for w in weights}
    return [
        round(by_date[d] * 10) if d in by_date else 0
        for d in (today - timedelta(days=n) for n in range(days - 1, -1, -1))
    ]


def weight_state(
    today: date_type, series: Sequence[int], *, logged: int = 0, error: str = ""
) -> str:
    last = next((n for n in reversed(list(series)) if n > 0), 800)
    state: dict[str, Any] = {
        "v": 1,
        "r": revision(),
        "d": f"{today:%d.%m}",
        "w": list(series),
        "c": last,
        "l": logged,
    }
    if error:
        state["e"] = _clip(error, _ERROR_MAX)
    return _fit(state)


def skincare_spec(slot: str, items: Sequence[dict]) -> WidgetSpec:
    return WidgetSpec(
        kind=KIND_SKINCARE,
        html=template(KIND_SKINCARE),
        chat_data=skincare_state(slot, items),
    )


def weight_spec(today: date_type, series: Sequence[int], *, logged: int = 0) -> WidgetSpec:
    return WidgetSpec(
        kind=KIND_WEIGHT,
        html=template(KIND_WEIGHT),
        chat_data=weight_state(today, series, logged=logged),
    )
