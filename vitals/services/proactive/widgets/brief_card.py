"""The morning brief as a card: the header's numbers drawn, the model's words below.

The card reads the same stored brief the text message is rendered from, so the two
can never disagree: every number and every "off" call comes from :mod:`compose`,
and the widget only paints what it is handed. It sends no requests at all
(``queries=False``): the day-plan buttons stay ordinary inline buttons under the
card and go through the same callback path as before.

State (UTF-8 JSON, at most 1024 bytes)::

    {"v":1, "r":rev, "h":"сб, 26 июля",
     "t":[[label, value, unit, meta, norm, tone, fill, tick], …],   recovery tiles
     "p":"…",                                         night not scored yet
     "o":[[label, text, tone, note], …],              bedroom · yesterday · weight
     "w":[tenths of kg × 14, 0 = no reading],         weight sparkline
     "d":"Сегодня по шаблону: …", "f":1}              day line, buttons below

``tone`` is 1 (better than his norm), -1 (worse, or the bedroom was off) or 0.
``fill``/``tick`` are 0-100 positions on the tile's bar (today and his norm), -1
when there is nothing honest to draw. Anything optional is simply absent.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_type, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.services.proactive import compose, day_plan
from vitals.services.proactive.channels import Buttons, Notifier, WidgetNotifier, WidgetSpec
from vitals.services.proactive.widgets import state

logger = logging.getLogger(__name__)

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

# key, label, unit, higher is better, 0-100 scale (else drawn against his norm)
_TILES = (
    ("sleep_score", "Сон", "", True, True),
    ("hrv_avg", "HRV", "мс", True, False),
    ("resting_hr", "Пульс покоя", "уд/мин", False, False),
    ("body_battery_high", "Body Battery", "", True, True),
)
# A metric with no fixed scale is drawn on 0…(the larger of today and the norm)
# plus this headroom, so the two marks never sit on the bar's very end.
_HEADROOM = 1.25
_SPARK_DAYS = 14
_TEXT_MAX = 90


def _clip(text: str, limit: int = _TEXT_MAX) -> str:
    # Line breaks only: ``split()`` would also eat the narrow no-break spaces
    # that group digits.
    text = " ".join(str(text).splitlines()).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pct(value: float, scale: float) -> int:
    if scale <= 0:
        return -1
    return max(0, min(100, round(value / scale * 100)))


def _tile(garmin: dict, baseline: dict, key: str, label: str, unit: str,
          higher_better: bool, percent: bool) -> Optional[list]:
    raw = garmin.get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    try:
        mean = float(baseline.get(key))
    except (TypeError, ValueError):
        mean = None

    tone, norm = 0, ""
    if mean and abs(value - mean) / abs(mean) >= compose._BASELINE_NOTABLE:
        better = value > mean if higher_better else value < mean
        tone = 1 if better else -1
        # The arrow is where today sits (above or below), the colour is whether
        # that is good — two separate facts, so a low resting HR reads "↓", calm.
        norm = f"{'↑' if value > mean else '↓'} норма {compose._num(mean)}"

    if percent:
        fill, tick = _pct(value, 100), (_pct(mean, 100) if mean is not None else -1)
    elif mean:
        scale = max(value, mean) * _HEADROOM
        fill, tick = _pct(value, scale), _pct(mean, scale)
    else:
        # No norm yet and no fixed scale: a bar would be a length with no meaning.
        fill, tick = -1, -1

    meta = compose._sleep_span(garmin) if key == "sleep_score" else ""
    return [label, compose._num(value), unit, _clip(meta, 32), norm, tone, fill, tick]


def _int(value) -> str:
    """``8421 → "8 421"`` with a narrow no-break space, as a number on a card reads."""
    return f"{round(float(value)):,}".replace(",", " ")


def _air_row(night: Optional[dict]) -> Optional[list]:
    """Bedroom air: the plain numbers on the line, what was off on the line below.

    Whether it was off is :func:`compose.environment_parts`' call, so the card and
    the text brief always agree; only the wording is shorter here."""
    parts = compose.environment_parts(night)
    if parts is None:
        return None
    off = parts[1]
    co2 = night.get("co2") or {}
    temp = (night.get("temperature") or {}).get("mean")
    humidity = (night.get("humidity") or {}).get("mean")
    thresholds = night.get("thresholds") or {}
    numbers = []
    if co2.get("median") is not None:
        numbers.append(f"CO₂ {_int(co2['median'])}")
    if temp is not None:
        numbers.append(f"{compose._decimal(temp)} °C")
    if humidity is not None:
        numbers.append(f"{round(float(humidity))}%")

    notes = []
    if off:
        warn, above = thresholds.get("co2_warn"), co2.get("minutes_above_warn") or 0
        usual = (night.get("baseline") or {}).get("co2_median")
        if warn is not None and above >= compose._CO2_MINUTES_NOTABLE:
            notes.append(f"CO₂ > {_int(warn)} — {compose._duration(above)}")
        elif usual:
            notes.append(f"CO₂ выше обычного ({_int(usual)})")
        low, high = thresholds.get("temp_sleep_min"), thresholds.get("temp_sleep_max")
        if temp is not None and low is not None and high is not None and not low <= temp <= high:
            word = "жарко" if temp > high else "холодно"
            notes.append(f"{word}, твои {compose._num(low)}–{compose._num(high)} °C")
    text = " · ".join(numbers) or parts[0]
    return ["Спальня", _clip(text, 40), -1 if off else 0, _clip(" · ".join(notes), 60)]


def _yesterday_row(day: Optional[dict]) -> Optional[list]:
    """Yesterday's final activity: steps and calories, the rest as a quiet note."""
    if compose.yesterday_block(day) is None:
        return None
    main, notes = [], []
    if day.get("steps") is not None:
        main.append(f"{_int(day['steps'])} шагов")
    if day.get("active_calories") is not None:
        main.append(f"{_int(day['active_calories'])} ккал")
    if day.get("intensity_minutes"):
        notes.append(f"{_int(day['intensity_minutes'])} мин интенсивности")
    # Same rule as the text line for when the evening count is worth mentioning.
    line = compose.yesterday_block(day).text
    if "(вечером было" in line and day.get("evening_steps") is not None:
        notes.append(f"вечером было {_int(day['evening_steps'])}")
    return ["Вчера", " · ".join(main) or "—", 0, _clip(" · ".join(notes), 60)]


def _date_label(on_date: date_type) -> str:
    return f"{_WEEKDAYS[on_date.weekday()]}, {on_date.day} {_MONTHS[on_date.month - 1]}"


def weight_series(weights: Sequence[Any], today: date_type, days: int = _SPARK_DAYS) -> list[int]:
    """The last ``days`` days ending today, tenths of kg; 0 where nothing was weighed."""
    by_date = {w.date: w.weight_kg for w in weights}
    return [
        round(by_date[d] * 10) if d in by_date else 0
        for d in (today - timedelta(days=n) for n in range(days - 1, -1, -1))
    ]


def build_state(
    ctx: dict,
    on_date: date_type,
    *,
    has_buttons: bool,
    series: Sequence[int] = (),
) -> str:
    """The card's chat state from a stored brief's context. Never over the cap."""
    garmin = ctx.get("garmin") or {}
    baseline = garmin.get("baseline") or {}
    data: dict[str, Any] = {"v": 1, "r": state.revision(), "h": _date_label(on_date)}

    tiles = [t for spec in _TILES if (t := _tile(garmin, baseline, *spec)) is not None]
    if tiles:
        data["t"] = tiles
    elif garmin.get("night_pending"):
        data["p"] = compose.LINE_NIGHT_PENDING

    rows: list[list] = []
    air = _air_row(ctx.get("environment"))
    if air is not None:
        rows.append(air)
    moved = _yesterday_row(ctx.get("yesterday"))
    if moved is not None:
        rows.append(moved)
    weight = ctx.get("weight") or {}
    if weight.get("latest_kg") is not None:
        text = f"{compose._decimal(weight['latest_kg'])} кг"
        slope = weight.get("trend_kg_per_week")
        note = ""
        if slope is not None:
            text += f" · {slope:+.2f} кг/нед".replace(".", ",").replace("-", "−")
            marker = (weight.get("noise_markers") or [None])[0]
            if marker:
                reason = (marker.get("reason") or "").strip()
                note = _clip(f"тренд зашумлён{f': {reason}' if reason else ''}", 60)
        rows.append(["Вес", text, -1 if note else 0, note])
        if sum(1 for n in series if n > 0) >= 2:
            data["w"] = list(series)
    if rows:
        data["o"] = rows

    day = day_plan.day_block(ctx.get("day"))
    if day is not None:
        data["d"] = _clip(day.text)
        if has_buttons:
            data["f"] = 1

    return _fit(data)


def _fit(data: dict[str, Any]) -> str:
    """Drop the least needed parts until the state fits Telegram's 1024 bytes."""
    for drop in ((), ("w",), ("w", "o"), ("w", "o", "d", "f")):
        trimmed = {k: v for k, v in data.items() if k not in drop}
        text = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) <= state.STATE_MAX_BYTES:
            return text
    return json.dumps({"v": 1, "r": data.get("r", 0), "h": data.get("h", "")}, ensure_ascii=False)


def narrative(content: str, ctx: dict) -> str:
    """The model's paragraph from a stored brief, without the header above it.

    The header is printed by code from the same stored context, so re-rendering it
    gives the exact prefix of the stored text. A brief that does not start with it
    (built by an older version, edited) yields "" rather than a caption that
    repeats the numbers the card already shows."""
    blocks = compose.header_blocks(ctx)
    day = day_plan.day_block(ctx.get("day"))
    if day is not None:
        blocks.append(day)
    header = compose.render(blocks)
    if not header:
        return content.strip()
    if not content.startswith(header):
        return ""
    return content[len(header):].strip()


async def spec_for(
    session: AsyncSession, row: Any, on_date: date_type, *, has_buttons: bool
) -> Optional[WidgetSpec]:
    """The card for a stored brief, or ``None`` (the text brief then goes as is).

    Never raises: the card is a nicer way to show a brief that must go out anyway."""
    try:
        from vitals.services import weight_service

        ctx = row.context_json or {}
        weights = await weight_service.list_active_weights(
            session, start=on_date - timedelta(days=_SPARK_DAYS - 1), end=on_date
        )
        return WidgetSpec(
            kind=state.KIND_BRIEF,
            html=state.template(state.KIND_BRIEF),
            chat_data=build_state(
                ctx, on_date, has_buttons=has_buttons, series=weight_series(weights, on_date)
            ),
            caption=narrative(row.content or "", ctx),
            keyboard=True,
            queries=False,
        )
    except Exception:
        logger.warning("brief card not built; sending the text brief", exc_info=True)
        return None


async def redraw_day(
    notifier: Optional[Notifier],
    sent: Any,
    message_id: str,
    answers: dict,
    buttons: Optional[Buttons],
) -> bool:
    """A day-plan tap under the card: its day line and its buttons, redrawn.

    ``sent`` is the journal row of the message. Starts from the state the card was
    sent with (journalled beside it), so nothing else on the card moves. Returns
    whether the message was a brief card at all."""
    payload = (getattr(sent, "payload", None) or {}) if sent is not None else {}
    if payload.get("widget") != state.KIND_BRIEF or not isinstance(notifier, WidgetNotifier):
        return False
    try:
        data = json.loads(payload.get("widget_state") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict) or data.get("v") != 1:
        return True
    if data.get("d"):
        data["d"] = _clip(day_plan.redraw(data["d"], answers, has_buttons=bool(buttons)))
    data.pop("f", None)
    if buttons:
        data["f"] = 1
    data["r"] = state.revision()
    chat_data = _fit(data)
    try:
        await notifier.edit_widget_data(message_id, chat_data)
        await notifier.edit_buttons(message_id, buttons or None)
    except Exception:
        logger.warning("could not redraw brief card %s", message_id, exc_info=True)
        return True
    # The next tap starts from this state, not the morning's.
    sent.payload = {**payload, "widget_state": chat_data}
    return True
