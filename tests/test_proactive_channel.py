"""The delivery channel: the webhook door, the budget, and the echo loop.

What's guarded here is everything that is silent when it breaks. A webhook that
accepts a forged call, a retry that logs the same evening twice, a budget that
counts replies and quietly gags the bot mid-conversation — none of those show up
as an error anywhere, so each gets a test.
"""
from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from vitals.models.proactive import Notification
from vitals.models.raw_payload import RawPayload
from vitals.models.signals import Signal
from vitals.services import signals_service
from vitals.services.proactive import day_plan, delivery, inbound

# The bot only speaks when the ``signals`` module is on — the same switch the
# owner flips in Settings, and it defaults off.
pytestmark = pytest.mark.usefixtures("signals_module_on")

CHAT_ID = "424242"
WEBHOOK_PATH = "s3cr3t-path"
WEBHOOK_SECRET = "s3cr3t-header"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}

NOON = datetime(2026, 7, 26, 12, 0)
NIGHT = datetime(2026, 7, 26, 3, 0)
# Inside the default quiet window (02:00–10:00) and a perfectly normal hour for
# the brief the owner scheduled himself.
MORNING = datetime(2026, 7, 26, 9, 0)


class FakeNotifier:
    """A channel that records instead of sending — the seam in one screenful."""

    channel = "telegram"

    def __init__(self, *, fail: bool = False):
        self.sent: list[dict] = []
        self.acks: list[tuple[str, str]] = []
        self.edits: list[dict] = []
        self._fail = fail
        self._next_id = 700

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        if self._fail:
            raise RuntimeError("telegram is having a bad minute")
        self._next_id += 1
        self.sent.append(
            {"text": text, "buttons": buttons, "reply_to": reply_to, "id": str(self._next_id)}
        )
        return str(self._next_id)

    async def answer_callback(self, callback_id, text="") -> None:
        self.acks.append((callback_id, text))

    async def edit(self, message_id, text, *, buttons=None) -> None:
        self.edits.append({"message_id": message_id, "text": text, "buttons": buttons})


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def bot_env(monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("VITALS_TELEGRAM_CHAT_ID", CHAT_ID)
    monkeypatch.setenv("VITALS_TELEGRAM_WEBHOOK_PATH", WEBHOOK_PATH)
    monkeypatch.setenv("VITALS_TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)


@pytest_asyncio.fixture
async def bot_client(client, bot_env):
    """The app with a fake channel wired in. Yields ``(client, notifier)``."""
    from web.main import app
    from web.routers.telegram import get_notifier

    fake = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: fake
    yield client, fake


@pytest.fixture
def parses_to(monkeypatch):
    """Pin what the "LLM" returns for any message; no network, no key."""
    items: list[dict] = []

    def _set(new_items):
        items[:] = new_items

    monkeypatch.setattr(
        inbound, "make_signal_parser", lambda known=None: (lambda _text: list(items))
    )
    return _set


def _text_update(update_id, text, *, chat=CHAT_ID, message_id=5, reply_to=None):
    message = {"message_id": message_id, "chat": {"id": int(chat)}, "text": text}
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": message}


def _tap_update(update_id, data, *, chat=CHAT_ID, callback_id="cb-1", text=None):
    message = {"message_id": 9, "chat": {"id": int(chat)}}
    if text is not None:
        message["text"] = text
    return {
        "update_id": update_id,
        "callback_query": {"id": callback_id, "data": data, "message": message},
    }


async def _signals(session) -> list[Signal]:
    return list((await session.execute(select(Signal))).scalars().all())


# ── The door ──────────────────────────────────────────────────────────────────
async def test_wrong_secret_header_is_rejected(bot_client):
    c, fake = bot_client
    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "привет"),
                     headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert r.status_code == 401
    assert fake.sent == []


async def test_missing_secret_header_is_rejected(bot_client):
    c, _ = bot_client
    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "привет"))
    assert r.status_code == 401


async def test_wrong_path_is_rejected(bot_client):
    c, _ = bot_client
    r = await c.post("/tg/guessed-it", json=_text_update(1, "привет"), headers=HEADERS)
    assert r.status_code == 401


async def test_non_ascii_path_is_rejected_not_crashed(bot_client):
    """compare_digest refuses non-ASCII str — a prober must get 401, not a 500."""
    c, _ = bot_client
    r = await c.post("/tg/привет", json=_text_update(1, "hi"), headers=HEADERS)
    assert r.status_code == 401


async def test_unconfigured_webhook_fails_closed(client, monkeypatch):
    monkeypatch.setenv("VITALS_TELEGRAM_WEBHOOK_PATH", "")
    monkeypatch.setenv("VITALS_TELEGRAM_WEBHOOK_SECRET", "")
    r = await client.post("/tg/anything", json=_text_update(1, "hi"), headers=HEADERS)
    assert r.status_code == 401


async def test_foreign_chat_is_swallowed_silently(bot_client, parses_to, db_session):
    """200 and the bin: a 403 would tell a prober they found a live endpoint."""
    c, fake = bot_client
    parses_to([{"kind": "state", "key": "sleepiness", "value_num": 4}])

    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "спать хочу", chat="999"),
                     headers=HEADERS)

    assert r.status_code == 200
    assert await _signals(db_session) == []
    assert fake.sent == []


async def test_cross_origin_header_does_not_block_the_webhook(bot_client, parses_to):
    """C5: the CSRF origin check must not fire on a path that has its own secret."""
    c, fake = bot_client
    parses_to([{"kind": "state", "key": "sleepiness", "value_num": 4}])

    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "спать хочу"),
                     headers={**HEADERS, "Origin": "https://api.telegram.org"})

    assert r.status_code == 200
    assert len(fake.sent) == 1


# ── Capture + echo ────────────────────────────────────────────────────────────
async def test_text_becomes_signals_plus_an_echo_with_an_undo_button(
    bot_client, parses_to, db_session
):
    c, fake = bot_client
    parses_to([
        {"kind": "symptom", "key": "headache", "value_num": 4, "note": "голова раскалывается"},
        {"kind": "exposure", "key": "caffeine_late", "at_time": "22:00", "note": "кофе в 22"},
    ])

    r = await c.post(f"/tg/{WEBHOOK_PATH}",
                     json=_text_update(1, "Голова раскалывается, кофе в 22"), headers=HEADERS)
    assert r.status_code == 200

    rows = await _signals(db_session)
    assert {row.key for row in rows} == {"headache", "caffeine_late"}
    assert len({row.batch_id for row in rows}) == 1

    # The raw message is in the lake under the update's own id.
    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "tg:1")
    )).scalars().first()
    assert raw is not None and raw.payload["text"].startswith("Голова")

    assert len(fake.sent) == 1
    echo = fake.sent[0]
    # His own words, the key the row was filed under, and the value. Without the
    # key the echo cannot be checked: the number alone reads the same whether the
    # fact landed on the existing key or opened a fresh synonym for it.
    assert "голова раскалывается → headache 4/5" in echo["text"]
    assert "кофе в 22 → caffeine_late в 22:00" in echo["text"]
    label, payload = echo["buttons"][0]
    assert label == "не то"
    assert payload == f"{inbound.CB_MISPARSE}{rows[0].batch_id}"


async def test_a_message_with_no_facts_is_kept_and_answered_without_alarm(
    bot_client, parses_to, db_session
):
    """The evening block asks «как день?» — «весь день за компом» is a good answer
    that simply holds no state, symptom or exposure. Saying "разобрать не смог" to
    the answer it just asked for makes a working bot look broken."""
    from vitals.models.system_alert import SystemAlert

    c, fake = bot_client
    parses_to([])

    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "ну такое"), headers=HEADERS)

    assert await _signals(db_session) == []
    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "tg:1")
    )).scalars().first()
    assert raw is not None
    assert fake.sent[0]["text"].startswith("Записал.")
    assert "не смог" not in fake.sent[0]["text"]
    assert fake.sent[0]["buttons"] is None
    # Nothing broke, so nothing to raise: an alert here would cry wolf daily.
    assert (await db_session.execute(select(SystemAlert))).scalars().all() == []


async def test_the_off_switch_stops_the_parse_and_the_reply_but_keeps_the_text(
    bot_client, db_session, monkeypatch
):
    """The switch is for the expensive and the outgoing half — a model call per
    message and every word back. It is not an amnesia switch: a message written
    while the bot was off is still his message, and dropping it on the floor is
    worse than either thing it was switched off to stop."""
    from vitals.services import modules_service

    c, fake = bot_client
    await modules_service.set_module_enabled(db_session, key="signals", enabled=False)
    await db_session.commit()

    def _never(*a, **kw):
        raise AssertionError("a switched-off module must not reach the parser")

    monkeypatch.setattr(inbound, "make_signal_parser", _never)

    r = await c.post(
        f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "башка трещит"), headers=HEADERS
    )

    # 200 all the same: anything else and Telegram retries the update forever.
    assert r.status_code == 200
    assert await _signals(db_session) == []
    assert fake.sent == []
    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "tg:1")
    )).scalars().first()
    assert raw is not None and raw.payload["text"] == "башка трещит"
    # Left pending on purpose: the re-parse sweep turns it into signals whenever
    # the module comes back on.
    assert raw.processed_at is None


async def test_a_tap_while_the_module_is_off_is_ignored(bot_client, db_session):
    """A tap answers a question this bot asked — with the module off there is
    nothing asking, so it is dropped rather than stored."""
    from vitals.services import modules_service

    c, fake = bot_client
    await modules_service.set_module_enabled(db_session, key="signals", enabled=False)
    await db_session.commit()
    tomorrow = date(2026, 7, 27)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{tomorrow.isoformat()}:where:remote"),
                 headers=HEADERS)

    assert await signals_service.get_day_context(db_session, tomorrow) is None
    assert fake.acks == []


async def test_a_dead_parser_raises_an_alert_that_clears_on_recovery(
    bot_client, db_session, monkeypatch
):
    """No key, no balance, upstream down — swallowed whole, a week of that is
    indistinguishable from a week of messages that held no facts. And once the
    parser is back, the alert must clear itself instead of lying there stale."""
    from vitals.models.system_alert import SystemAlert
    from vitals.services import signals_service

    c, fake = bot_client

    def _boom(known=None):
        async def _parse(_text):
            raise RuntimeError("upstream down")

        return _parse

    monkeypatch.setattr(inbound, "make_signal_parser", _boom)

    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "башка трещит"), headers=HEADERS)
    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(2, "спать хочу"), headers=HEADERS)

    alerts = (await db_session.execute(select(SystemAlert))).scalars().all()
    assert len(alerts) == 1, "one open alert while it's down, not one per message"
    assert alerts[0].alert_key == signals_service.PARSER_FAILED_ALERT_KEY
    assert alerts[0].severity == "warn"
    # The message still survives: raw first, parse second.
    assert (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "tg:1")
    )).scalars().first() is not None

    # The parser recovers → the alert must not linger as a stale warning forever.
    def _recovered(known=None):
        async def _parse(_text):
            return [{"kind": "state", "key": "sleepiness", "value_num": 5}]

        return _parse

    monkeypatch.setattr(inbound, "make_signal_parser", _recovered)
    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(3, "спать хочу"), headers=HEADERS)

    active = (await db_session.execute(
        select(SystemAlert).where(SystemAlert.resolved_at.is_(None))
    )).scalars().all()
    assert not any(a.alert_key == signals_service.PARSER_FAILED_ALERT_KEY for a in active)


async def test_repeated_update_id_is_not_processed_twice(bot_client, parses_to, db_session):
    """Telegram retries until it gets a 200 — a retry must be a no-op."""
    c, fake = bot_client
    parses_to([{"kind": "state", "key": "sleepiness", "value_num": 5}])
    update = _text_update(77, "спать пиздец хочу")

    await c.post(f"/tg/{WEBHOOK_PATH}", json=update, headers=HEADERS)
    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=update, headers=HEADERS)

    assert r.status_code == 200
    assert len(await _signals(db_session)) == 1
    assert len(fake.sent) == 1


async def test_the_message_is_committed_before_the_model_is_called(db_session, monkeypatch):
    """Telegram re-sends an update it got no 200 for, and the model call in the
    middle takes 5-20 seconds. The retry arrives on its own connection and can
    only see what is *committed* — so a raw row still sitting in the request's
    open transaction means the retry finds no trace of the first attempt and pays
    for a second parse and a second reply to the same message."""
    from sqlalchemy.ext.asyncio import AsyncSession

    fake = FakeNotifier()
    commits: list[int] = []
    real_commit = AsyncSession.commit

    async def _counting_commit(self):
        await real_commit(self)
        commits.append(1)

    monkeypatch.setattr(AsyncSession, "commit", _counting_commit)

    durable: list[bool] = []

    async def _parse(_text):
        # Recorded, not asserted: ``ingest_text`` swallows anything the parser
        # raises, so an assertion here would be turned into a warning and lost.
        durable.append(bool(commits))
        return []

    await inbound.handle_text(
        db_session, "спать хочу", notifier=fake, external_id="tg:1", parse=_parse
    )

    assert durable == [True]


async def test_a_crash_in_the_handler_is_still_answered_with_200(bot_client, monkeypatch):
    """A 500 makes Telegram retry the same update for hours, each retry another
    model call. The message is already in the lake by then and the re-parse sweep
    finishes what this run didn't."""
    c, _ = bot_client

    async def _boom(*a, **kw):
        raise RuntimeError("something broke mid-update")

    monkeypatch.setattr(inbound, "handle_update", _boom)

    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "спать хочу"), headers=HEADERS)

    assert r.status_code == 200


async def test_a_message_after_midnight_lands_on_the_day_that_just_ended(db_session):
    """«кофе поздно» written at 00:30 is about the evening just spent. Filed under
    the fresh calendar date it lands in tomorrow's brief, and tonight's — the one
    that would have explained the sleep it ruined — never sees it."""
    from freezegun import freeze_time

    fake = FakeNotifier()

    async def _parse(_text):
        return [{"kind": "exposure", "key": "caffeine_late", "note": "кофе поздно"}]

    # 21:30 UTC = 00:30 local (Europe/Chisinau is UTC+3 in July).
    with freeze_time("2026-07-26 21:30:00"):
        await inbound.handle_text(db_session, "кофе поздно", notifier=fake, parse=_parse)
    # …and the normal case is untouched: an afternoon message is today's.
    with freeze_time("2026-07-27 12:00:00"):
        await inbound.handle_text(db_session, "кофе поздно", notifier=fake, parse=_parse)

    assert sorted(row.date for row in await _signals(db_session)) == [
        date(2026, 7, 26), date(2026, 7, 27),
    ]


# ── Taps ──────────────────────────────────────────────────────────────────────
async def test_undo_tap_flags_the_whole_batch_but_keeps_it(bot_client, parses_to, db_session):
    c, fake = bot_client
    parses_to([
        {"kind": "state", "key": "sleepiness", "value_num": 5},
        {"kind": "symptom", "key": "headache", "value_num": 2},
    ])
    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "всё плохо"), headers=HEADERS)
    batch_id = (await _signals(db_session))[0].batch_id

    r = await c.post(f"/tg/{WEBHOOK_PATH}",
                     json=_tap_update(2, f"{inbound.CB_MISPARSE}{batch_id}"), headers=HEADERS)

    assert r.status_code == 200
    rows = await _signals(db_session)
    assert len(rows) == 2 and all(row.misparse for row in rows)
    # Gone from the charts, still on the table.
    assert await signals_service.list_signals(db_session) == []
    assert fake.acks == [("cb-1", "Убрал из графиков")]


async def test_context_tap_answers_the_day_it_was_asked_about(bot_client, db_session):
    """The date rides in the payload: the evening block asks about tomorrow, and a
    tap that lands after midnight must still answer that day."""
    c, fake = bot_client
    tomorrow = date(2026, 7, 27)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{tomorrow.isoformat()}:where:remote"),
                 headers=HEADERS)
    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(2, f"{inbound.CB_CONTEXT}{tomorrow.isoformat()}:gym:0",
                                  callback_id="cb-2"),
                 headers=HEADERS)

    ctx = await signals_service.get_day_context(db_session, tomorrow)
    assert ctx is not None
    # Second tap merges into the first answer rather than replacing it.
    assert ctx.answers == {"where": "remote", "gym": False}
    assert fake.acks[-1] == ("cb-2", "Записал")


async def test_a_slash_command_is_answered_not_captured(bot_client, db_session, monkeypatch):
    """``/start`` is the first thing anyone ever sends a bot. Parsing it costs a
    model call and replies "разобрать не смог" — which reads as broken."""
    c, fake = bot_client

    def _never(*a, **kw):
        raise AssertionError("a command must not reach the parser")

    monkeypatch.setattr(inbound, "make_signal_parser", _never)

    r = await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "/start"), headers=HEADERS)

    assert r.status_code == 200
    assert await _signals(db_session) == []
    assert fake.sent[-1]["text"] == inbound.COMMAND_REPLY


async def test_a_retried_slash_command_is_answered_once(bot_client, db_session):
    """The command branch used to answer and leave, writing nothing to the lake —
    so Telegram's retry found no trace of the update and got a second identical
    wall of text."""
    c, fake = bot_client
    update = _text_update(1, "/start")

    await c.post(f"/tg/{WEBHOOK_PATH}", json=update, headers=HEADERS)
    await c.post(f"/tg/{WEBHOOK_PATH}", json=update, headers=HEADERS)

    assert len(fake.sent) == 1
    raw = (await db_session.execute(
        select(RawPayload).where(RawPayload.external_id == "tg:1")
    )).scalars().first()
    # Marked done: «/start» is not a message waiting to become signals, so the
    # re-parse sweep must never hand it to the parser.
    assert raw is not None and raw.processed_at is not None


async def test_a_tap_outside_the_question_registry_is_dropped(bot_client, db_session):
    """Telegram keeps old keyboards tappable forever: a button from before a
    question was renamed must not write a key nothing reads back."""
    c, _ = bot_client
    tomorrow = date(2026, 7, 27)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{tomorrow.isoformat()}:remote:1"),
                 headers=HEADERS)
    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(2, f"{inbound.CB_CONTEXT}{tomorrow.isoformat()}:where:луна",
                                  callback_id="cb-2"),
                 headers=HEADERS)

    assert await signals_service.get_day_context(db_session, tomorrow) is None


# 2026-07-27 is a Monday: the default template calls it "в офисе · без зала".
MONDAY = date(2026, 7, 27)
# The evening goes out as two messages: the day just spent, then the one ahead.
# A keyboard belongs to a message, so each carries only the questions it can ask.
EVENING_RECAP = f"Итог дня: 8000 шагов\n\n{day_plan.ASK_DAY}"
EVENING_PLAN = f"Завтра: в офисе · без зала\n{day_plan.HINT_FIX}"


async def test_a_tap_redraws_the_message_it_came_from(bot_client, db_session):
    """A tap used to leave nothing but a grey toast: the line still read out the
    template's guess and the same keyboard sat under it — which looks like «не
    нажалось» and gets tapped again."""
    c, fake = bot_client

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{MONDAY.isoformat()}:where:remote",
                                  text=EVENING_PLAN),
                 headers=HEADERS)

    assert len(fake.edits) == 1
    edit = fake.edits[0]
    assert edit["message_id"] == "9"
    assert "Завтра: удалёнка · без зала" in edit["text"]
    # …and the question he just answered is gone from the keyboard, while the one
    # he hasn't stays tappable.
    payloads = [data for _, data in edit["buttons"]]
    assert not any(":where:" in data for data in payloads)
    assert any(":gym:" in data for data in payloads)
    # The recap question is not this keyboard's to ask: rebuilding it here would
    # hang «тяжёлый день» under a message about tomorrow.
    assert not any(":load:" in data for data in payloads)


async def test_a_tap_on_the_recap_rebuilds_the_recap_keyboard(bot_client, db_session):
    """The evening sends two keyboards. A tap carries only its key, so the redraw
    infers which one it came off — get that wrong and answering «тяжёлый день»
    replaces it with tomorrow's «удалёнка»."""
    c, fake = bot_client

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{MONDAY.isoformat()}:load:heavy",
                                  text=EVENING_RECAP),
                 headers=HEADERS)

    edit = fake.edits[0]
    # Nothing else to recap, so the keyboard goes — and «Как день?» stays, because
    # a tap answered the one-tap half, not the invitation to write.
    assert edit["buttons"] is None
    assert day_plan.ASK_DAY in edit["text"]
    assert "Завтра" not in edit["text"]


async def test_the_last_answer_takes_the_keyboard_and_the_hint_with_it(bot_client, db_session):
    """Nothing left to correct: a hint about a keyboard, with the keyboard gone,
    is the message pointing at buttons that aren't there."""
    c, fake = bot_client
    text = EVENING_PLAN
    for i, (key, value) in enumerate((("where", "remote"), ("gym", "1"))):
        await c.post(f"/tg/{WEBHOOK_PATH}",
                     json=_tap_update(i + 1, f"{inbound.CB_CONTEXT}{MONDAY.isoformat()}:{key}:{value}",
                                      callback_id=f"cb-{i}", text=text),
                     headers=HEADERS)
        text = fake.edits[-1]["text"]  # the next tap sees the redrawn message

    assert fake.edits[-1]["buttons"] is None
    assert day_plan.HINT_FIX not in text
    assert "Завтра: удалёнка · зал" in text


async def test_a_tap_on_the_brief_stops_calling_the_answer_a_template(bot_client, db_session):
    """The morning brief says «Сегодня по шаблону» while the day is still a guess.
    A tap is the owner speaking — the redrawn line must not keep crediting the
    template for what he just said."""
    c, fake = bot_client

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_tap_update(1, f"{inbound.CB_CONTEXT}{MONDAY.isoformat()}:where:remote",
                                  text="Сегодня по шаблону: в офисе · без зала"),
                 headers=HEADERS)

    assert fake.edits[-1]["text"] == "Сегодня: удалёнка · без зала"


async def test_a_redraw_the_channel_refuses_does_not_lose_the_answer(bot_client, db_session, monkeypatch):
    """Telegram rejects an edit that changes nothing, and old messages stop being
    editable at all. The answer is already stored by then — a raised update would
    only buy hours of retries."""
    c, fake = bot_client

    async def _refuse(*a, **kw):
        raise RuntimeError("message can't be edited")

    monkeypatch.setattr(fake, "edit", _refuse)

    r = await c.post(f"/tg/{WEBHOOK_PATH}",
                     json=_tap_update(1, f"{inbound.CB_CONTEXT}{MONDAY.isoformat()}:where:remote",
                                      text=EVENING_PLAN),
                     headers=HEADERS)

    assert r.status_code == 200
    ctx = await signals_service.get_day_context(db_session, MONDAY)
    assert ctx is not None and ctx.answers == {"where": "remote"}


# ── Replies ───────────────────────────────────────────────────────────────────
async def test_reply_to_our_message_is_answered_not_captured(
    bot_client, parses_to, db_session, monkeypatch
):
    c, fake = bot_client
    parses_to([{"kind": "state", "key": "sleepiness", "value_num": 5}])
    sent = await delivery.send(db_session, fake, text="Утро: сон 6:10, HRV 42.",
                               category=delivery.CATEGORY_BRIEF, now=NOON)
    asked = {}

    async def _answer(question, context, facts=""):
        asked["question"], asked["context"] = question, context
        return "HRV чуть ниже твоей нормы."

    monkeypatch.setattr(inbound, "answer_reply", _answer)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_text_update(1, "а HRV это плохо?", reply_to=int(sent.external_id)),
                 headers=HEADERS)

    # A question is a question, not a symptom — nothing lands in signals.
    assert await _signals(db_session) == []
    assert asked["question"] == "а HRV это плохо?"
    assert "HRV 42" in asked["context"]
    assert fake.sent[-1]["text"] == "HRV чуть ниже твоей нормы."


async def test_reply_falls_back_to_a_line_when_the_model_is_down(
    bot_client, db_session, monkeypatch
):
    c, fake = bot_client
    sent = await delivery.send(db_session, fake, text="Утро: сон 6:10.",
                               category=delivery.CATEGORY_BRIEF, now=NOON)

    async def _boom(question, context, facts=""):
        raise RuntimeError("no key")

    monkeypatch.setattr(inbound, "answer_reply", _boom)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_text_update(1, "почему?", reply_to=int(sent.external_id)),
                 headers=HEADERS)

    assert "Сейчас не отвечу" in fake.sent[-1]["text"]


async def test_a_question_typed_without_a_reply_is_answered_not_parsed(
    bot_client, db_session, monkeypatch
):
    """Telegram-reply is a feature almost nobody uses on mobile. Typed plainly,
    «почему hrv просел?» went to the fact parser and came back as «фактов для
    графиков тут не нашёл» — the single most broken-looking thing the bot says."""
    c, fake = bot_client

    def _never(*a, **kw):
        raise AssertionError("a question must not reach the signal parser")

    monkeypatch.setattr(inbound, "make_signal_parser", _never)
    asked = {}

    async def _answer(question, context, facts=""):
        asked["question"] = question
        return "HRV просел после позднего кофеина."

    monkeypatch.setattr(inbound, "answer_reply", _answer)

    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "почему hrv просел?"),
                 headers=HEADERS)

    assert await _signals(db_session) == []
    assert asked["question"] == "почему hrv просел?"
    assert fake.sent[-1]["text"] == "HRV просел после позднего кофеина."


async def test_a_fact_that_opens_with_a_question_word_is_still_captured(
    bot_client, parses_to, db_session, monkeypatch
):
    """The predicate matches the first *word*, not a prefix: «что-то тошнит» is a
    symptom, and routing it to Q&A would lose the row it was written for."""
    c, _ = bot_client
    parses_to([{"kind": "symptom", "key": "nausea", "value_num": 3, "note": "что-то тошнит"}])

    async def _never(*a, **kw):
        raise AssertionError("a symptom must not go to the Q&A path")

    monkeypatch.setattr(inbound, "answer_reply", _never)

    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "что-то тошнит"), headers=HEADERS)

    assert [row.key for row in await _signals(db_session)] == ["nausea"]


async def test_the_question_path_is_given_the_days_numbers(
    bot_client, db_session, monkeypatch
):
    """Fed one message's prose and nothing else, the model cannot see the HRV it
    is being asked about, so the only honest answer it has is "в тексте этого
    нет". The brief already stored the day it was built from — read that."""
    from vitals.enums import DigestKind
    from vitals.integrations import llm_client
    from vitals.models.milestones import DOMAIN as INSIGHTS_DOMAIN, WeeklyDigest

    c, fake = bot_client
    db_session.add(WeeklyDigest(
        date=date(2026, 7, 26),
        domain=INSIGHTS_DOMAIN,
        kind=DigestKind.DAILY_BRIEF.value,
        content="Утро: разбор дня.",
        context_json={"hrv": 42, "sleep_hours": 6.1},
    ))
    await db_session.flush()

    seen = {}

    async def _complete(self, prompt, **kwargs):
        seen["prompt"] = prompt
        return "HRV 42 — ниже твоей нормы."

    monkeypatch.setattr(llm_client.LLMClient, "complete_text", _complete)

    await c.post(f"/tg/{WEBHOOK_PATH}", json=_text_update(1, "почему hrv просел?"),
                 headers=HEADERS)

    assert "42" in seen["prompt"] and "6.1" in seen["prompt"]
    assert "почему hrv просел?" in seen["prompt"]
    assert fake.sent[-1]["text"] == "HRV 42 — ниже твоей нормы."


async def test_a_question_without_a_reply_still_sees_what_the_bot_just_said(
    bot_client, db_session, monkeypatch
):
    """«что за ключ странный на второе» is about the echo sent a minute earlier.
    Typed plainly (nobody uses Telegram's Reply), it used to reach the model with
    no message attached, and the answer was a guess about the 2nd of the month."""
    c, fake = bot_client
    await delivery.send(db_session, fake, text="Утро: разбор дня.",
                        category=delivery.CATEGORY_BRIEF, now=NOON)
    await delivery.send(db_session, fake, text="Записал:\n• спать охота → sleepiness 3/5\n"
                                              "• энергос → sugar 1 serving в 17:00",
                        category=delivery.CATEGORY_ECHO, now=NOON)
    asked = {}

    async def _answer(question, context, facts=""):
        asked["context"] = context
        return "sugar — ключ для сахара, 1 порция."

    monkeypatch.setattr(inbound, "answer_reply", _answer)

    await c.post(f"/tg/{WEBHOOK_PATH}",
                 json=_text_update(1, "что за ключ странный на второе"), headers=HEADERS)

    assert "sugar 1 serving" in asked["context"]
    # Oldest first, so the message being asked about is the one nearest the question.
    assert asked["context"].index("Утро") < asked["context"].index("Записал")
    assert fake.sent[-1]["text"] == "sugar — ключ для сахара, 1 порция."


# ── Budget & quiet hours ──────────────────────────────────────────────────────
async def test_budget_cuts_the_fifth_self_initiated_message(db_session):
    fake = FakeNotifier()
    for i in range(delivery.DAILY_BUDGET):
        assert await delivery.send(db_session, fake, text=f"нудж {i}",
                                   category=delivery.CATEGORY_NUDGE, now=NOON) is not None

    assert await delivery.send(db_session, fake, text="пятый",
                               category=delivery.CATEGORY_NUDGE, now=NOON) is None
    assert len(fake.sent) == delivery.DAILY_BUDGET


async def test_the_budget_never_gags_a_reply(db_session):
    """The rule that is easiest to get wrong: after four nudges the bot must still
    answer you, or a spent budget reads as a broken bot."""
    fake = FakeNotifier()
    for i in range(delivery.DAILY_BUDGET):
        await delivery.send(db_session, fake, text=f"нудж {i}",
                            category=delivery.CATEGORY_NUDGE, now=NOON)

    assert await delivery.send(db_session, fake, text="ответ",
                               category=delivery.CATEGORY_REPLY, now=NOON) is not None
    assert await delivery.send(db_session, fake, text="эхо",
                               category=delivery.CATEGORY_ECHO, now=NOON) is not None
    # …and the exempt ones didn't quietly eat tomorrow's budget either.
    assert await delivery.sent_today(db_session, on_date=NOON.date()) == delivery.DAILY_BUDGET


async def test_budget_is_per_calendar_day(db_session):
    fake = FakeNotifier()
    for i in range(delivery.DAILY_BUDGET):
        await delivery.send(db_session, fake, text=f"нудж {i}",
                            category=delivery.CATEGORY_NUDGE, now=NOON)

    tomorrow_noon = NOON.replace(day=NOON.day + 1)
    assert await delivery.send(db_session, fake, text="завтрашний",
                               category=delivery.CATEGORY_NUDGE, now=tomorrow_noon) is not None


async def test_quiet_hours_hold_initiative_but_not_answers(db_session):
    fake = FakeNotifier()
    assert await delivery.send(db_session, fake, text="нудж в три ночи",
                               category=delivery.CATEGORY_NUDGE, now=NIGHT) is None
    assert await delivery.send(db_session, fake, text="эхо в три ночи",
                               category=delivery.CATEGORY_ECHO, now=NIGHT) is not None
    assert len(fake.sent) == 1


async def test_quiet_hours_hold_nudges_but_not_the_times_he_set_himself(db_session):
    """The brief and the evening block go out at an hour typed by hand into the
    same settings card. If quiet hours could cancel them, one field would silently
    override another — a brief scheduled for 09:00 that simply never arrives."""
    fake = FakeNotifier()

    assert await delivery.send(db_session, fake, text="утренний разбор",
                               category=delivery.CATEGORY_BRIEF, now=MORNING) is not None
    assert await delivery.send(db_session, fake, text="итог дня",
                               category=delivery.CATEGORY_EVENING, now=MORNING) is not None
    # The bot's own idea of a good moment still waits for the window to close.
    assert await delivery.send(db_session, fake, text="надж",
                               category=delivery.CATEGORY_NUDGE, now=MORNING) is None
    assert len(fake.sent) == 2


async def test_quiet_hours_hold_environment_alerts(db_session):
    fake = FakeNotifier()
    assert await delivery.send(db_session, fake, text="душно в спальне",
                               category=delivery.CATEGORY_ENVIRONMENT, now=NIGHT) is None
    assert await delivery.send(db_session, fake, text="душно в спальне",
                               category=delivery.CATEGORY_ENVIRONMENT, now=NOON) is not None
    assert len(fake.sent) == 1


async def test_the_budget_never_gags_an_environment_alert(db_session):
    fake = FakeNotifier()
    for i in range(delivery.DAILY_BUDGET):
        await delivery.send(db_session, fake, text=f"нудж {i}",
                            category=delivery.CATEGORY_NUDGE, now=NOON)

    assert await delivery.send(db_session, fake, text="пятый",
                               category=delivery.CATEGORY_NUDGE, now=NOON) is None
    assert await delivery.send(db_session, fake, text="душно в спальне",
                               category=delivery.CATEGORY_ENVIRONMENT, now=NOON) is not None
    assert len(fake.sent) == delivery.DAILY_BUDGET + 1


def test_quiet_window_can_wrap_past_midnight():
    """Settings let the owner set the window; 23:00–07:00 must not mean "never"."""
    from datetime import time

    assert delivery.in_quiet_hours(time(23, 30), start=time(23, 0), end=time(7, 0))
    assert delivery.in_quiet_hours(time(2, 0), start=time(23, 0), end=time(7, 0))
    assert not delivery.in_quiet_hours(time(12, 0), start=time(23, 0), end=time(7, 0))


async def test_dedupe_key_makes_a_second_send_a_no_op(db_session):
    fake = FakeNotifier()
    first = await delivery.send(db_session, fake, text="бриф", category=delivery.CATEGORY_BRIEF,
                                dedupe_key="brief:2026-07-26", now=NOON)
    second = await delivery.send(db_session, fake, text="бриф", category=delivery.CATEGORY_BRIEF,
                                 dedupe_key="brief:2026-07-26", now=NOON)

    assert first is not None and second is None
    assert len(fake.sent) == 1


async def test_a_failed_send_is_not_journalled_and_costs_no_budget(db_session):
    """Telegram having a bad minute must not roll back the caller's DB work, and
    must not silently spend a slot on a message nobody received."""
    broken = FakeNotifier(fail=True)

    assert await delivery.send(db_session, broken, text="нудж",
                               category=delivery.CATEGORY_NUDGE, now=NOON) is None
    assert (await db_session.execute(select(Notification))).scalars().all() == []
    assert await delivery.sent_today(db_session, on_date=NOON.date()) == 0


async def test_no_channel_configured_is_silence_not_an_error(db_session):
    assert await delivery.send(db_session, None, text="нудж",
                               category=delivery.CATEGORY_NUDGE, now=NOON) is None


# ── The Telegram wire format ──────────────────────────────────────────────────
@pytest.fixture
def captured_payload(monkeypatch):
    """Intercept the Bot API call — the payload shape is invisible until prod."""
    from vitals.services.proactive import channels

    seen: dict = {}

    async def _call(self, method, payload):
        seen["method"], seen["payload"] = method, payload
        return {"message_id": 4242}

    monkeypatch.setattr(channels.TelegramNotifier, "_call", _call)
    return seen


async def test_buttons_and_reply_are_sent_in_telegram_shape(captured_payload):
    from vitals.services.proactive import channels

    notifier = channels.TelegramNotifier("token", CHAT_ID)
    message_id = await notifier.send("текст", buttons=[("не то", "mis:abc")], reply_to="55")

    assert message_id == "4242"
    payload = captured_payload["payload"]
    assert payload["chat_id"] == CHAT_ID
    assert payload["reply_markup"] == {
        "inline_keyboard": [[{"text": "не то", "callback_data": "mis:abc"}]]
    }
    # A reply whose target was deleted must still arrive.
    assert payload["reply_to_message_id"] == 55
    assert payload["allow_sending_without_reply"] is True


async def test_an_overlong_message_is_truncated_not_dropped(captured_payload):
    """Telegram rejects >4096 chars outright: a long brief would just never land."""
    from vitals.services.proactive import channels

    await channels.TelegramNotifier("token", CHAT_ID).send("я" * 5000)

    text = captured_payload["payload"]["text"]
    assert len(text) == 4096 and text.endswith("…")


def test_build_notifier_needs_both_token_and_chat(monkeypatch):
    from vitals.config import load_config
    from vitals.services.proactive import channels

    monkeypatch.setenv("VITALS_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("VITALS_TELEGRAM_CHAT_ID", "")
    assert channels.build_notifier(load_config()) is None

    monkeypatch.setenv("VITALS_TELEGRAM_CHAT_ID", CHAT_ID)
    notifier = channels.build_notifier(load_config())
    assert isinstance(notifier, channels.Notifier)
    assert notifier.channel == "telegram"
