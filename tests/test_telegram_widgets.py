"""Telegram widgets: the request schema, the owner check, replay safety, the
size budget of the static HTML, the chat state, and the fallback to plain messages.

A widget is code that runs on someone else's server and phones home with a
64-byte string, so the guarded failures are the quiet ones: a request from the
wrong user acted on, a payload that is more than it looks, a double tap that logs
twice, a block-level conflict waved through, a card that doesn't fit Telegram's
limits and is refused only in production.
"""
from __future__ import annotations

import json
import re
import zlib
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from vitals.models.proactive import Notification
from vitals.models.skincare import SkincareCheck
from vitals.services import modules_service, skincare_service
from vitals.services.proactive import delivery, inbound
from vitals.services.proactive import skincare as reminders
from vitals.services.proactive.channels import WidgetNotifier, WidgetSpec
from vitals.services.proactive.widgets import payload, state
from vitals.services.proactive.widgets.handler import is_owner_query

from tests.test_skincare_checks import _product, _retinoid_peel_rule

pytestmark = pytest.mark.usefixtures("signals_module_on")

OWNER = "424242"
WED = datetime(2026, 10, 21, 22, 30)
EVENING_DAY = date(2026, 10, 21)


class WidgetFake:
    """A channel with both faces: plain messages and widgets, all recorded."""

    channel = "telegram"

    def __init__(self, *, widgets_fail: bool = False):
        self.sent: list[dict] = []
        self.widgets: list[tuple[str, WidgetSpec]] = []
        self.answers: list[tuple[str, str]] = []
        self.state_edits: list[tuple[str, str]] = []
        self.edits: list[dict] = []
        self.widget_buttons: list[list] = []
        self.button_edits: list[tuple[str, list]] = []
        self._widgets_fail = widgets_fail
        self._next = 900

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append({"text": text, "buttons": list(buttons or [])})
        self._next += 1
        return str(self._next)

    async def answer_callback(self, callback_id, text="") -> None: ...

    async def edit(self, message_id, text, *, buttons=None) -> None:
        self.edits.append({"id": message_id, "text": text})

    async def send_widget(self, caption, widget, *, buttons=None) -> str:
        if self._widgets_fail:
            raise RuntimeError("Telegram sendWidget failed (400): bots may not send widgets")
        self.widgets.append((caption, widget))
        self.widget_buttons.append(list(buttons or []))
        self._next += 1
        return str(self._next)

    async def edit_widget_data(self, message_id, chat_data) -> None:
        self.state_edits.append((message_id, chat_data))

    async def edit_buttons(self, message_id, buttons) -> None:
        self.button_edits.append((message_id, list(buttons or [])))

    async def answer_widget_query(self, query_id, data="") -> None:
        self.answers.append((query_id, data))


@pytest.fixture
def widgets_on(monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("VITALS_TELEGRAM_CHAT_ID", OWNER)
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "true")


@pytest.fixture
async def skincare_on(db_session):
    await modules_service.set_module_enabled(db_session, key="skincare", enabled=True)
    await db_session.commit()


def _query(update_id, data, *, message_id, user=OWNER, chat=OWNER, chat_type="private", qid=None):
    wq = {
        "id": qid or f"77{update_id}",
        "from": {"id": int(user), "is_bot": False, "first_name": "X"},
        "message_id": message_id,
        "data": data,
    }
    if chat is not None:
        wq["chat"] = {"id": int(chat), "type": chat_type}
    return {"update_id": update_id, "widget_query": wq}


async def _send_checklist(db_session, fake, *names_flags):
    ids = []
    for name, flag in names_flags:
        ids.append((await _product(db_session, name, flag=flag)).id)
    row = await reminders.send_slot(db_session, fake, "evening", now=WED)
    await db_session.commit()
    return ids, int(row.external_id)


async def _checks(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(SkincareCheck))).scalar()


# ── Payload schema ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "data, expected",
    [
        ("sk:1:12", payload.SkincareTick(12, True)),
        ("sk:0:12", payload.SkincareTick(12, False)),
        ("sk:a", payload.SkincareAll()),
    ],
)
def test_valid_payloads_parse(data, expected):
    assert payload.parse(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        None, 7, b"sk:a", "", " sk:a", "sk:a ", "sk:a\n", "SK:A", "sk:2:1", "sk:1:0", "sk:1:01",
        "sk:1:-3", "sk:1:1.5", "sk:1:1; DROP TABLE x", "sk:1:" + "9" * 10, "sk:1:١٢",
        "wt:823", "wt:", "wt:82.3",
        "rf", "eval:1", "sk:1:12:extra", "x" * 65, "sk:a" + "a" * 70,
    ],
)
def test_everything_else_is_refused(data):
    assert payload.parse(data) is None


def test_the_action_list_is_closed_under_random_junk():
    import random

    rng = random.Random(7)
    alphabet = "sk:wt01a9 ;'\"\\%{}$\u0436"
    for _ in range(3000):
        junk = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        action = payload.parse(junk)
        if action is not None:
            # whatever got through is one of the two shapes, nothing else
            assert re.fullmatch(r"sk:[01]:[1-9]\d{0,8}|sk:a", junk)


# ── Owner check ──────────────────────────────────────────────────────────────
def test_owner_check_needs_both_user_and_private_chat():
    ok = _query(1, "sk:a", message_id=1)["widget_query"]
    assert is_owner_query(ok, OWNER)
    assert not is_owner_query(ok, "")
    assert not is_owner_query(ok, "1")
    assert not is_owner_query(_query(1, "sk:a", message_id=1, user="999")["widget_query"], OWNER)
    assert not is_owner_query(_query(1, "sk:a", message_id=1, chat="999")["widget_query"], OWNER)
    assert not is_owner_query(
        _query(1, "sk:a", message_id=1, chat_type="supergroup")["widget_query"], OWNER
    )
    assert not is_owner_query(_query(1, "sk:a", message_id=1, chat=None)["widget_query"], OWNER)
    assert not is_owner_query({"from": True, "chat": {"id": 1, "type": "private"}}, "1")


@pytest.mark.usefixtures("widgets_on", "skincare_on")
@pytest.mark.parametrize(
    "overrides",
    [{"user": "999"}, {"chat": "999"}, {"chat": None}, {"chat_type": "group"}],
)
async def test_a_request_from_anyone_else_is_dropped_unanswered(db_session, overrides):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))

    await inbound.handle_update(
        db_session, _query(1, f"sk:1:{ids[0]}", message_id=mid, **overrides), notifier=fake
    )

    assert fake.answers == [] and fake.state_edits == []
    assert await _checks(db_session) == 0


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_the_webhook_door_drops_other_chats_and_forwarded_copies(db_session, monkeypatch):
    assert inbound.chat_id_of(_query(1, "sk:a", message_id=1, chat="999")) == "999"
    # a forwarded copy of a shared widget has no chat at all → never the owner's
    assert inbound.chat_id_of(_query(1, "sk:a", message_id=1, chat=None)) is None
    fwd = {"update_id": 5, "shared_widget_query": {"id": "1", "from": {"id": int(OWNER)}, "data": "sk:a"}}
    assert inbound.chat_id_of(fwd) is None


# ── Skincare card ────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_flag_on_sends_the_checklist_as_a_widget_with_state(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Дифферин", None), ("Крем", None))

    assert fake.sent == [] and len(fake.widgets) == 1
    caption, spec = fake.widgets[0]
    assert "Вечерний уход" in caption
    data = json.loads(spec.chat_data)
    assert [i[1] for i in data["i"]] == ["Дифферин", "Крем"] and all(i[2] == 0 for i in data["i"])
    row = (await db_session.execute(select(Notification))).scalars().one()
    assert row.payload["widget"] == "skincare" and row.external_id == str(mid)


async def test_flag_off_is_the_old_plain_message(db_session, skincare_on, monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "")
    fake = WidgetFake()
    await _send_checklist(db_session, fake, ("Крем", None))
    assert fake.widgets == [] and len(fake.sent) == 1 and fake.sent[0]["buttons"]


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_a_refused_widget_falls_back_to_text_and_buttons(db_session):
    fake = WidgetFake(widgets_fail=True)
    _, mid = await _send_checklist(db_session, fake, ("Крем", None))

    assert len(fake.sent) == 1 and fake.sent[0]["buttons"]
    row = (await db_session.execute(select(Notification))).scalars().one()
    assert "widget" not in row.payload  # journalled as the plain message it became
    # …and a tap on the fallback keyboard still works through the old path
    await inbound.handle_update(
        db_session,
        {"update_id": 3, "callback_query": {"id": "c", "data": fake.sent[0]["buttons"][0][1],
                                            "message": {"message_id": mid, "chat": {"id": int(OWNER)}}}},
        notifier=fake,
    )
    assert await _checks(db_session) == 1 and fake.edits


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_tick_logs_once_answers_with_state_and_pushes_it(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Дифферин", None), ("Крем", None))

    await inbound.handle_update(db_session, _query(1, f"sk:1:{ids[0]}", message_id=mid), notifier=fake)

    assert await _checks(db_session) == 1
    (qid, answer), = fake.answers
    assert qid == "771"
    assert [i[2] for i in json.loads(answer)["i"]] == [1, 0]
    assert fake.state_edits == [(str(mid), answer)]


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_replays_do_not_double_log(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))

    # Telegram retrying the same update, then the user tapping "check" again
    # from a widget that hadn't redrawn yet.
    same = _query(1, f"sk:1:{ids[0]}", message_id=mid)
    await inbound.handle_update(db_session, same, notifier=fake)
    await inbound.handle_update(db_session, same, notifier=fake)
    await inbound.handle_update(db_session, _query(2, f"sk:1:{ids[0]}", message_id=mid), notifier=fake)

    assert await _checks(db_session) == 1
    assert len(fake.answers) == 2  # the retried update id is dropped, the new tap answered

    await inbound.handle_update(db_session, _query(3, f"sk:0:{ids[0]}", message_id=mid), notifier=fake)
    await inbound.handle_update(db_session, _query(4, f"sk:0:{ids[0]}", message_id=mid), notifier=fake)
    assert await _checks(db_session) == 0


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_complete_all_and_unknown_product(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("A", None), ("B", None))

    await inbound.handle_update(db_session, _query(1, "sk:1:99999", message_id=mid), notifier=fake)
    assert await _checks(db_session) == 0
    assert json.loads(fake.answers[-1][1])["e"] == "Нет в списке"

    await inbound.handle_update(db_session, _query(2, "sk:a", message_id=mid), notifier=fake)
    assert await _checks(db_session) == 2


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_a_blocking_conflict_is_an_error_line_never_an_override(db_session):
    await _retinoid_peel_rule(db_session)
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Дифферин", "retinoid"), ("Пилинг", "peel"))

    await inbound.handle_update(db_session, _query(1, f"sk:1:{ids[0]}", message_id=mid), notifier=fake)
    await inbound.handle_update(db_session, _query(2, f"sk:1:{ids[1]}", message_id=mid), notifier=fake)

    assert await _checks(db_session) == 1  # the peel was not recorded
    answer = json.loads(fake.answers[-1][1])
    assert "Конфликт" in answer["e"] and [i[2] for i in answer["i"]] == [1, 0]
    log = await skincare_service.get_log(db_session, EVENING_DAY)
    assert log.retinoid is True and not log.peel


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_the_widget_never_passes_override(monkeypatch, db_session):
    seen = []
    real = skincare_service.set_check

    async def spy(*a, **kw):
        seen.append(kw.get("override"))
        return await real(*a, **kw)

    monkeypatch.setattr(skincare_service, "set_check", spy)
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))
    await inbound.handle_update(db_session, _query(1, f"sk:1:{ids[0]}", message_id=mid), notifier=fake)
    assert seen == [False]


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_a_tick_in_the_app_redraws_the_widget_state(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))
    await skincare_service.set_check(db_session, on_date=EVENING_DAY, product_id=ids[0], slot="evening", done=True)
    await reminders.sync_sent(db_session, fake, EVENING_DAY, "evening")

    assert fake.edits == []  # no editMessageText on a widget message
    (edited_id, data), = fake.state_edits
    assert edited_id == str(mid) and json.loads(data)["i"][0][2] == 1


@pytest.mark.usefixtures("skincare_on")
async def test_a_request_with_widgets_switched_off_changes_nothing(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_CHAT_ID", OWNER)
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "true")
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "")

    await inbound.handle_update(db_session, _query(1, f"sk:1:{ids[0]}", message_id=mid), notifier=fake)

    assert await _checks(db_session) == 0 and fake.answers == [("771", "")]


@pytest.mark.usefixtures("widgets_on", "skincare_on")
async def test_garbage_and_foreign_messages_are_answered_empty_and_ignored(db_session):
    fake = WidgetFake()
    ids, mid = await _send_checklist(db_session, fake, ("Крем", None))

    await inbound.handle_update(db_session, _query(1, "sk:1:1; DROP", message_id=mid), notifier=fake)
    await inbound.handle_update(db_session, _query(2, f"sk:1:{ids[0]}", message_id=424242), notifier=fake)
    await inbound.handle_update(db_session, _query(3, "wt:800", message_id=mid), notifier=fake)  # not an action
    wq = _query(4, f"sk:1:{ids[0]}", message_id=mid)
    wq["widget_query"]["message_id"] = "not-int"
    await inbound.handle_update(db_session, wq, notifier=fake)

    assert await _checks(db_session) == 0
    assert [a[1] for a in fake.answers] == ["", "", "", ""]


# ── State and templates ──────────────────────────────────────────────────────
def test_skincare_state_always_fits_the_state_cap():
    items = [{"product_id": 10**8 + n, "name": "Очень длинное название средства " * 3, "done": n % 2}
             for n in range(30)]
    text = state.skincare_state("evening", items, error="Ошибка " * 40)
    assert len(text.encode("utf-8")) <= state.STATE_MAX_BYTES
    parsed = json.loads(text)
    assert parsed["i"] and all(len(i[1]) <= 18 for i in parsed["i"])


def test_state_contains_only_what_the_card_draws():
    text = state.skincare_state("morning", [{"product_id": 3, "name": "SPF", "done": False, "how": "secret how-to",
                                            "flag": "retinoid", "done_at": "2026-10-21T08:00"}])
    assert set(json.loads(text)) == {"v", "r", "t", "i"}
    assert "secret" not in text and "retinoid" not in text and "2026" not in text


@pytest.mark.parametrize("kind", [state.KIND_SKINCARE, state.KIND_BRIEF])
def test_templates_fit_telegrams_limits_and_stay_offline(kind):
    html = state.template(kind)
    raw = html.encode("utf-8")
    assert len(raw) <= 32768
    assert len(zlib.compress(raw, 9)) <= 4096 * 0.8  # real headroom under the 4096 cap
    assert "\x00" not in html
    for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "eval(",
                   "new Function", "<script src", "<link", "<iframe", "@import", "http://", "https://",
                   "{{", "{%", "localStorage", "location", "window.open", "openLink", "wallet"):
        assert banned not in html, banned
    # untrusted text is painted with textContent only
    assert "innerHTML" not in html and "document.write" not in html
    # every request the template can make is on the action list
    sent = set(re.findall(r"(?:request|send)\('([a-z]+:)", html))
    assert sent <= {"sk:"}


def test_the_telegram_notifier_implements_the_widget_protocol():
    from vitals.services.proactive.channels import TelegramNotifier

    assert isinstance(TelegramNotifier("t", "1"), WidgetNotifier)


# ── Morning brief card ───────────────────────────────────────────────────────
from vitals.models.milestones import WeeklyDigest  # noqa: E402
from vitals.services.proactive import brief, day_plan  # noqa: E402
from vitals.services.proactive.widgets import brief_card  # noqa: E402

from tests.test_daily_brief import DAY, FakeLLM, _patch_job, _seed_day  # noqa: E402

CARD_DAY = date(2026, 11, 21)
BASELINE = {"sleep_score": 81, "hrv_avg": 55, "resting_hr": 51, "body_battery_high": 78}
BAD_NIGHT = {"sleep_score": 74, "sleep_seconds": 24840, "sleep_start": "2026-11-21T01:12:00",
             "sleep_end": "2026-11-21T08:06:00", "hrv_avg": 48, "resting_hr": 54,
             "body_battery_high": 71, "baseline": BASELINE}
STUFFY_AIR = {"co2": {"median": 1180, "minutes_above_warn": 140}, "temperature": {"mean": 23.4},
              "humidity": {"mean": 41}, "baseline": {"co2_median": 820},
              "thresholds": {"co2_warn": 1000, "temp_sleep_min": 18, "temp_sleep_max": 22}}


def _card(ctx, **kw):
    has_buttons = kw.pop("has_buttons", False)
    return json.loads(brief_card.build_state(ctx, CARD_DAY, has_buttons=has_buttons, **kw))


def _tiles(data):
    return {t[0]: t for t in data["t"]}


def test_tiles_carry_the_norm_its_direction_and_whether_that_is_good():
    tiles = _tiles(_card({"garmin": BAD_NIGHT}))
    sleep, hrv, rhr = tiles["Сон"], tiles["HRV"], tiles["Пульс покоя"]
    # [label, value, unit, meta, norm, tone, fill, tick]
    assert sleep[1:3] == ["74", ""] and "6 ч 54 мин" in sleep[3] and "01:12–08:06" in sleep[3]
    assert sleep[4:] == ["↓ норма 81", -1, 74, 81]
    # a higher resting HR is the bad direction: arrow up, tone worse
    assert rhr[4] == "↑ норма 51" and rhr[5] == -1
    # no fixed scale: drawn against his norm with headroom, both marks inside the bar
    assert hrv[2] == "мс" and 0 < hrv[6] < hrv[7] < 100


def test_a_number_on_its_norm_is_quiet_and_no_norm_means_no_bar():
    calm = dict(BAD_NIGHT, hrv_avg=56, resting_hr=50)
    tiles = _tiles(_card({"garmin": calm}))
    assert tiles["HRV"][4:6] == ["", 0] and tiles["Пульс покоя"][4:6] == ["", 0]
    lower = dict(BAD_NIGHT, resting_hr=46)
    assert _tiles(_card({"garmin": lower}))["Пульс покоя"][4:6] == ["↓ норма 51", 1]
    fresh = _tiles(_card({"garmin": dict(BAD_NIGHT, baseline=None)}))
    assert fresh["HRV"][6:] == [-1, -1] and fresh["HRV"][4] == ""
    assert fresh["Сон"][6:] == [74, -1]  # a 0-100 score still has a bar, just no norm tick


def test_an_unscored_night_shows_the_pending_line_and_no_tiles():
    data = _card({"garmin": {"night_pending": True}})
    assert "t" not in data and data["p"] == brief.compose.LINE_NIGHT_PENDING


def test_bedroom_row_is_coloured_by_the_same_call_the_text_brief_makes():
    row = next(r for r in _card({"environment": STUFFY_AIR})["o"] if r[0] == "Спальня")
    assert row[1] == "CO₂ 1 180 · 23,4 °C · 41%" and row[2] == -1
    assert "2 ч 20 мин" in row[3] and "жарко" in row[3]
    assert brief.compose.environment_parts(STUFFY_AIR)[1] is True
    fine = dict(STUFFY_AIR, co2={"median": 760}, temperature={"mean": 20.5},
                baseline={"co2_median": 800})
    row = next(r for r in _card({"environment": fine})["o"] if r[0] == "Спальня")
    assert row[2] == 0 and row[3] == ""
    assert brief.compose.environment_parts(fine)[1] is False


def test_weight_row_sparkline_and_noise_warning():
    ctx = {"weight": {"latest_kg": 82.4, "trend_kg_per_week": -0.42,
                      "noise_markers": [{"reason": "креатин"}]}}
    data = _card(ctx, series=[0] * 12 + [825, 824])
    (row,) = data["o"]
    assert row[:3] == ["Вес", "82,4 кг · −0,42 кг/нед", -1] and "креатин" in row[3]
    assert data["w"][-2:] == [825, 824]
    assert "w" not in _card(ctx, series=[0] * 13 + [824])  # one point is not a line


def test_day_line_and_the_hint_ride_on_the_card():
    ctx = {"day": {"answers": {"where": "office", "gym": True}, "source": "template"}}
    data = _card(ctx, has_buttons=True)
    assert data["d"].startswith(day_plan.LINE_TODAY_PLANNED) and data["f"] == 1
    assert "f" not in _card(ctx)


def test_brief_state_always_fits_and_carries_nothing_extra():
    long = "очень длинная причина " * 40
    ctx = {"garmin": BAD_NIGHT, "environment": STUFFY_AIR,
           "yesterday": {"steps": 10**7, "active_calories": 10**6, "intensity_minutes": 999,
                         "evening_steps": 1},
           "weight": {"latest_kg": 82.4, "trend_kg_per_week": -0.4,
                      "noise_markers": [{"reason": long}]},
           "day": {"answers": {"where": "office", "gym": True, "load": "heavy"}, "source": "manual"},
           "glp1": {"dose": "secret"}, "signals": [{"text": "личная заметка"}],
           "nutrition": {"kcal": 2100}}
    text = brief_card.build_state(ctx, CARD_DAY, has_buttons=True,
                                  series=[800 + n for n in range(14)])
    assert len(text.encode("utf-8")) <= state.STATE_MAX_BYTES
    assert set(json.loads(text)) <= {"v", "r", "h", "t", "p", "o", "w", "d", "f"}
    assert "secret" not in text and "личная" not in text and "2100" not in text


def test_narrative_is_the_text_under_the_stored_header():
    ctx = {"garmin": BAD_NIGHT, "day": {"answers": {"where": "office"}, "source": "template"}}
    blocks = brief.compose.header_blocks(ctx) + [day_plan.day_block(ctx["day"])]
    header = brief.compose.render(blocks)
    assert brief_card.narrative(f"{header}\n\nСпи дольше.", ctx) == "Спи дольше."
    assert brief_card.narrative("Чужой текст\n\nСпи дольше.", ctx) == ""
    assert brief_card.narrative(header, ctx) == ""


@pytest.mark.usefixtures("all_modules_on", "widgets_on")
async def test_brief_goes_out_as_a_card_with_its_buttons_and_no_request_path(
    db_session, session_factory, monkeypatch
):
    fake = WidgetFake()
    _patch_job(monkeypatch, fake, FakeLLM("Восстановление в норме."))
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    await brief.brief_job(session_factory)

    assert fake.sent == [] and len(fake.widgets) == 1
    caption, spec = fake.widgets[0]
    assert caption == "Восстановление в норме."
    assert spec.kind == state.KIND_BRIEF and spec.queries is False and spec.keyboard is True
    assert fake.widget_buttons[0] and all(b[1].startswith("ctx:") for b in fake.widget_buttons[0])
    data = json.loads(spec.chat_data)
    assert _tiles(data)["Сон"][1] == "80" and data["f"] == 1
    row = (await db_session.execute(select(Notification))).scalars().one()
    assert row.payload["widget"] == "brief" and row.payload["widget_state"] == spec.chat_data
    # the journal and the stored brief keep the full text, as before
    assert row.payload["text"].endswith(day_plan.HINT_FIX)
    stored = (await db_session.execute(select(WeeklyDigest))).scalars().one()
    assert stored.content.endswith("Восстановление в норме.")


@pytest.mark.usefixtures("all_modules_on", "widgets_on")
async def test_a_refused_brief_card_is_the_plain_brief(db_session, session_factory, monkeypatch):
    fake = WidgetFake(widgets_fail=True)
    _patch_job(monkeypatch, fake, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    await brief.brief_job(session_factory)

    assert len(fake.sent) == 1 and fake.sent[0]["buttons"]
    assert fake.sent[0]["text"].endswith(day_plan.HINT_FIX)


@pytest.mark.usefixtures("all_modules_on")
async def test_flag_off_brief_is_the_plain_brief(db_session, session_factory, monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "")
    fake = WidgetFake()
    _patch_job(monkeypatch, fake, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    await brief.brief_job(session_factory)

    assert fake.widgets == [] and len(fake.sent) == 1


@pytest.mark.usefixtures("all_modules_on", "widgets_on")
async def test_a_day_button_under_the_card_redraws_its_state_not_its_text(
    db_session, session_factory, monkeypatch
):
    fake = WidgetFake()
    _patch_job(monkeypatch, fake, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)
    await brief.brief_job(session_factory)
    mid = int((await db_session.execute(select(Notification))).scalars().one().external_id)
    label, data = fake.widget_buttons[0][0]

    tap = {"update_id": 9, "callback_query": {
        "id": "c1", "data": data,
        "message": {"message_id": mid, "chat": {"id": int(OWNER), "type": "private"},
                    "caption": "x"}}}
    await inbound.handle_update(db_session, tap, notifier=fake)
    await db_session.commit()

    assert fake.edits == []  # never editMessageText on a card
    (edited_id, new_state), = fake.state_edits
    new = json.loads(new_state)
    assert edited_id == str(mid) and new["d"].startswith(day_plan.LINE_TODAY) and label in new["d"]
    (bid, buttons), = fake.button_edits
    assert bid == str(mid) and all(b[1] != data for b in buttons)
    if not buttons:
        assert "f" not in new
    row = (await db_session.execute(select(Notification))).scalars().one()
    await db_session.refresh(row)
    assert row.payload["widget_state"] == new_state  # the next tap starts from here


async def test_telegram_send_widget_payload(monkeypatch):
    from vitals.services.proactive.channels import TelegramNotifier

    calls = []

    async def fake_call(self, method, payload):
        calls.append((method, payload))
        return {"message_id": 5}

    monkeypatch.setattr(TelegramNotifier, "_call", fake_call)
    n = TelegramNotifier("t", "1")
    card = WidgetSpec(kind="brief", html="<p>", chat_data="{}", keyboard=True, queries=False)
    assert await n.send_widget("", card, buttons=[("зал", "ctx:x")]) == "5"
    method, sent = calls[-1]
    assert method == "sendWidget" and "allow_queries" not in sent and "caption" not in sent
    assert sent["protect_content"] is True
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "ctx:x"

    await n.send_widget("подпись", WidgetSpec(kind="skincare", html="<p>", chat_data="{}"))
    assert calls[-1][1]["allow_queries"] is True and calls[-1][1]["caption"] == "подпись"
    await n.edit_buttons("5", None)
    assert calls[-1] == ("editMessageReplyMarkup",
                         {"chat_id": "1", "message_id": 5, "reply_markup": {"inline_keyboard": []}})
