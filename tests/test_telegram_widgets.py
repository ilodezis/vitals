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
from freezegun import freeze_time
from sqlalchemy import func, select

from vitals.models.proactive import Notification
from vitals.models.skincare import SkincareCheck
from vitals.models.weight import WeightLog
from vitals.services import modules_service, skincare_service, weight_service
from vitals.services.proactive import delivery, inbound
from vitals.services.proactive import skincare as reminders
from vitals.services.proactive.channels import WidgetNotifier, WidgetSpec
from vitals.services.proactive.widgets import cards, payload, state
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
        self._widgets_fail = widgets_fail
        self._next = 900

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append({"text": text, "buttons": list(buttons or [])})
        self._next += 1
        return str(self._next)

    async def answer_callback(self, callback_id, text="") -> None: ...

    async def edit(self, message_id, text, *, buttons=None) -> None:
        self.edits.append({"id": message_id, "text": text})

    async def send_widget(self, caption, widget) -> str:
        if self._widgets_fail:
            raise RuntimeError("Telegram sendWidget failed (400): bots may not send widgets")
        self.widgets.append((caption, widget))
        self._next += 1
        return str(self._next)

    async def edit_widget_data(self, message_id, chat_data) -> None:
        self.state_edits.append((message_id, chat_data))

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
        ("wt:823", payload.WeightLog(823)),
    ],
)
def test_valid_payloads_parse(data, expected):
    assert payload.parse(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        None, 7, b"sk:a", "", " sk:a", "sk:a ", "sk:a\n", "SK:A", "sk:2:1", "sk:1:0", "sk:1:01",
        "sk:1:-3", "sk:1:1.5", "sk:1:1; DROP TABLE x", "sk:1:" + "9" * 10, "sk:1:١٢",
        "wt:", "wt:82.3", "wt:0823", "wt:199", "wt:4001", "wt:99999", "wt:-5",
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
            # whatever got through is one of the three shapes, nothing else
            assert re.fullmatch(r"sk:[01]:[1-9]\d{0,8}|sk:a|wt:[1-9]\d{2,3}", junk)


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
    await inbound.handle_update(db_session, _query(3, "wt:800", message_id=mid), notifier=fake)  # wrong card kind
    wq = _query(4, f"sk:1:{ids[0]}", message_id=mid)
    wq["widget_query"]["message_id"] = "not-int"
    await inbound.handle_update(db_session, wq, notifier=fake)

    assert await _checks(db_session) == 0
    assert [a[1] for a in fake.answers] == ["", "", "", ""]


# ── Weight card ──────────────────────────────────────────────────────────────
async def _weights(db_session):
    return (await db_session.execute(select(WeightLog))).scalars().all()


async def _seed_week(db_session):
    for day, kg in ((19, 82.9), (20, 82.5)):
        await weight_service.log_weight(db_session, on_date=date(2026, 10, day), weight_kg=kg)
    await db_session.commit()


@pytest.mark.usefixtures("widgets_on")
@freeze_time("2026-10-21 09:00:00")
async def test_weight_card_is_offered_only_while_today_is_missing(db_session):
    await _seed_week(db_session)
    fake = WidgetFake()
    now = datetime(2026, 10, 21, 9, 0)

    row = await cards.send_weight_card(db_session, fake, now=now)
    again = await cards.send_weight_card(db_session, fake, now=now)

    assert row is not None and again is None and len(fake.widgets) == 1
    data = json.loads(fake.widgets[0][1].chat_data)
    assert data["w"] == [0, 0, 0, 0, 829, 825, 0] and data["c"] == 825 and data["l"] == 0


@pytest.mark.usefixtures("widgets_on")
@freeze_time("2026-10-21 09:00:00")
async def test_no_weight_card_when_today_is_already_logged_or_widgets_refused(db_session):
    now = datetime(2026, 10, 21, 9, 0)
    refused = WidgetFake(widgets_fail=True)
    assert await cards.send_weight_card(db_session, refused, now=now) is None
    assert refused.sent == []  # no text twin: nothing at all
    await weight_service.log_weight(db_session, on_date=date(2026, 10, 21), weight_kg=82.0)
    await db_session.commit()
    ok = WidgetFake()
    assert await cards.send_weight_card(db_session, ok, now=now) is None and ok.widgets == []


@freeze_time("2026-10-21 09:00:00")
async def test_weight_card_is_silent_when_the_flag_is_off(db_session, monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_WIDGETS", "")
    fake = WidgetFake()
    assert await cards.send_weight_card(db_session, fake) is None and fake.widgets == []


@pytest.mark.usefixtures("widgets_on")
@freeze_time("2026-10-21 09:00:00")
async def test_a_weight_tap_logs_once_and_replays_are_the_same_row(db_session):
    fake = WidgetFake()
    row = await cards.send_weight_card(db_session, fake, now=datetime(2026, 10, 21, 9, 0))
    await db_session.commit()
    mid = int(row.external_id)

    await inbound.handle_update(db_session, _query(1, "wt:823", message_id=mid), notifier=fake)
    await inbound.handle_update(db_session, _query(1, "wt:823", message_id=mid), notifier=fake)  # retry
    await inbound.handle_update(db_session, _query(2, "wt:823", message_id=mid), notifier=fake)  # second tap

    rows = await _weights(db_session)
    assert len(rows) == 1 and rows[0].weight_kg == 82.3 and rows[0].note == "telegram widget"
    assert json.loads(fake.answers[-1][1])["l"] == 823 and len(fake.answers) == 2

    await inbound.handle_update(db_session, _query(3, "wt:821", message_id=mid), notifier=fake)  # correction
    active = await weight_service.get_active_weight(db_session, date(2026, 10, 21))
    assert active.weight_kg == 82.1


@pytest.mark.usefixtures("widgets_on")
async def test_a_stale_weight_card_does_not_log(db_session):
    with freeze_time("2026-10-21 09:00:00"):
        fake = WidgetFake()
        row = await cards.send_weight_card(db_session, fake, now=datetime(2026, 10, 21, 9, 0))
        await db_session.commit()
    with freeze_time("2026-10-22 09:00:00"):
        await inbound.handle_update(db_session, _query(1, "wt:823", message_id=int(row.external_id)), notifier=fake)
        assert await _weights(db_session) == []
        assert json.loads(fake.answers[-1][1])["e"] == "Карточка устарела"


@pytest.mark.usefixtures("widgets_on")
@freeze_time("2026-10-21 09:00:00")
async def test_a_blocking_weight_conflict_is_reported_not_overridden(db_session, monkeypatch):
    from vitals.services import conflict_engine

    seen = []

    async def blocked(session, domain, proposed, *, override=False, **kw):
        seen.append(override)
        raise conflict_engine.ConflictBlocked([])

    monkeypatch.setattr(weight_service.conflict_engine, "enforce", blocked)
    fake = WidgetFake()
    row = await cards.send_weight_card(db_session, fake, now=datetime(2026, 10, 21, 9, 0))
    await db_session.commit()

    await inbound.handle_update(db_session, _query(1, "wt:823", message_id=int(row.external_id)), notifier=fake)

    assert seen == [False] and await _weights(db_session) == []
    assert "Конфликт" in json.loads(fake.answers[-1][1])["e"]


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
    w = json.loads(state.weight_state(date(2026, 10, 21), [0, 0, 0, 0, 0, 825, 0]))
    assert set(w) == {"v", "r", "d", "w", "c", "l"}


def test_weight_series_places_readings_on_their_days():
    class W:
        def __init__(self, d, kg):
            self.date, self.weight_kg = d, kg

    series = state.weight_series([W(date(2026, 10, 21), 82.3), W(date(2026, 10, 15), 83.0),
                                  W(date(2026, 10, 1), 90.0)], date(2026, 10, 21))
    assert series == [830, 0, 0, 0, 0, 0, 823]


@pytest.mark.parametrize("kind", [state.KIND_SKINCARE, state.KIND_WEIGHT])
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
    assert sent <= {"sk:", "wt:"}


def test_the_telegram_notifier_implements_the_widget_protocol():
    from vitals.services.proactive.channels import TelegramNotifier

    assert isinstance(TelegramNotifier("t", "1"), WidgetNotifier)
