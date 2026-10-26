"""The evening block, the week template, and whose answer wins.

Three things here fail *silently* if they regress, which is why each gets a test:

  * an evening block that asks about the wrong date (a job at 00:00 instead of
    23:45, or a button that says "today") collects context for a day that already
    happened — and nothing in the data ever looks wrong;
  * a tap that lands on a day where the template's guess was never parked erases
    the only material the template could learn from;
  * a brief that prefers the template to his actual answer gives advice for a day
    he explicitly said he isn't having.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from vitals.enums import Source
from vitals.models.app_settings import AppSetting
from vitals.models.proactive import Notification
from vitals.models.signals import Signal
from vitals.services import garmin_service, signals_service
from vitals.services.proactive import brief, day_plan, delivery, inbound
from vitals.utils.timeutils import local_naive_to_utc

# The bot only speaks when the ``signals`` module is on — the same switch the
# owner flips in Settings, and it defaults off.
pytestmark = pytest.mark.usefixtures("signals_module_on")

DAY = date(2026, 7, 26)          # Sunday
TOMORROW = DAY + timedelta(days=1)

GARMIN_RAW = {
    "summary": {
        "totalSteps": 8412,
        "activeKilocalories": 520,
        "moderateIntensityMinutes": 30,
        "vigorousIntensityMinutes": 15,
        "restingHeartRate": 52,
        "bodyBatteryHighestValue": 84,
    },
    "sleep": {"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}},
    "hrv": {"hrvSummary": {"lastNightAvg": 61}},
}


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append({"text": text, "buttons": buttons})
        return str(800 + len(self.sent))

    async def answer_callback(self, callback_id, text="") -> None:
        pass


class FakeLLM:
    digest_model = "fake/digest"
    brief_model = "fake/brief"

    def __init__(self):
        self.calls: list[dict] = []

    async def complete_text(self, prompt, *, model=None, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt})
        return "Норм, можно грузиться."


def _patch_evening(monkeypatch, notifier):
    from vitals.services.proactive import channels

    monkeypatch.setattr(channels, "build_notifier", lambda *a, **kw: notifier)
    monkeypatch.setattr(day_plan, "today_local", lambda: DAY)


# ── The 23:45 job ─────────────────────────────────────────────────────────────
async def test_evening_block_asks_about_calendar_tomorrow(
    db_session, session_factory, monkeypatch
):
    """Every plan button carries tomorrow's date, so a tap after midnight still
    lands on the day that was asked about — and the recap buttons carry today's,
    because they answer the day that just ended."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()

    await day_plan.evening_job(session_factory)

    recap, plan = notifier.sent
    assert "8412 шагов" in recap["text"]
    assert "520 ккал" in recap["text"]
    assert "45 мин интенсивности" in recap["text"]
    assert "Как день?" in recap["text"]
    for _, payload in recap["buttons"]:
        assert payload.startswith(f"{inbound.CB_CONTEXT}{DAY.isoformat()}:load:")

    assert "Завтра:" in plan["text"]
    assert plan["buttons"], "an evening block with no buttons asks nothing"
    for _, payload in plan["buttons"]:
        assert payload.startswith(f"{inbound.CB_CONTEXT}{TOMORROW.isoformat()}:")
        assert ":load:" not in payload, "how heavy tomorrow is cannot be answered tonight"

    journal = (await db_session.execute(select(Notification))).scalars().all()
    assert [n.category for n in journal] == [delivery.CATEGORY_EVENING] * 2
    assert [n.dedupe_key for n in journal] == [
        day_plan.dedupe_key(DAY),
        day_plan.plan_dedupe_key(DAY),
    ]


async def test_evening_block_parks_the_guess_even_if_nothing_is_tapped(
    db_session, session_factory, monkeypatch
):
    """``planned`` is only collectable at the moment the guess is made — a template
    that learns from the gap needs it written down whether or not he answers."""
    _patch_evening(monkeypatch, FakeNotifier())

    await day_plan.evening_job(session_factory)

    row = await signals_service.get_day_context(db_session, TOMORROW)
    assert row.planned == day_plan.DEFAULT_DAY
    assert not row.answers          # a parked guess is not an answer
    assert row.source == Source.TEMPLATE.value


async def test_evening_block_runs_twice_and_sends_once(
    db_session, session_factory, monkeypatch
):
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)

    await day_plan.evening_job(session_factory)
    await day_plan.evening_job(session_factory)

    # Two messages — the recap and the plan — and a replay adds neither.
    assert len(notifier.sent) == 2


async def test_evening_block_keeps_asking_what_is_still_unanswered(
    db_session, session_factory, monkeypatch
):
    """B6: one tap answers one question. Dropping the whole keyboard after it left
    tomorrow's other two questions with no way of ever being answered."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)
    await day_plan.record_answer(db_session, TOMORROW, "gym", True)
    await db_session.commit()

    await day_plan.evening_job(session_factory)

    payloads = {payload for _, payload in notifier.sent[1]["buttons"]}
    assert not [p for p in payloads if ":gym:" in p]
    assert f"ctx:{TOMORROW.isoformat()}:where:remote" in payloads


async def test_the_evening_buttons_say_they_are_about_tomorrow(
    db_session, session_factory, monkeypatch
):
    """A keyboard belongs to a message, not to a line. Merged, «тяжёлый день»
    sat two lines under «Как день?» and read as the answer to it while writing into
    tomorrow. Split, each question owns the buttons directly beneath it."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)

    await day_plan.evening_job(session_factory)

    recap, plan = notifier.sent
    # The recap needs no hint: «Как день?» is the last line above its keyboard.
    assert recap["text"].rstrip().endswith(day_plan.ASK_DAY)
    assert {label for label, _ in recap["buttons"]} == {
        "лёгкий день", "обычный день", "тяжёлый день"
    }
    assert "Завтра:" not in recap["text"]

    assert "Как день?" not in plan["text"]
    assert plan["text"].rstrip().endswith(day_plan.HINT_FIX)


async def test_evening_block_drops_the_summary_when_garmin_has_nothing(
    db_session, session_factory, monkeypatch
):
    """No Garmin row is a missing line, not a missing message: the question about
    tomorrow is the point of the evening block."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)

    await day_plan.evening_job(session_factory)

    text = notifier.sent[0]["text"]
    assert "Итог дня" not in text
    assert "Как день?" in text
    assert "Завтра:" in notifier.sent[1]["text"]


LATE = datetime.combine(DAY, datetime.min.time()).replace(hour=23, minute=45)


def _gmt(local: datetime) -> str:
    """A local wall-clock moment as Garmin's ``lastSyncTimestampGMT``."""
    return local_naive_to_utc(local).replace(tzinfo=None).isoformat(timespec="milliseconds")


class _PulseClient:
    """Stands in for GarminClient: today's summary is all the evening asks for."""

    summary: dict = {}
    calls: list = []
    is_configured = True

    @classmethod
    def from_config(cls, config=None, redis=None):
        return cls()

    async def fetch_summary(self, on_date):
        type(self).calls.append(on_date)
        return type(self).summary


def _patch_pulse(monkeypatch, summary):
    import vitals.integrations.garmin_client as gc

    _PulseClient.summary = summary
    _PulseClient.calls = []
    monkeypatch.setattr(gc, "GarminClient", _PulseClient)
    monkeypatch.setattr(garmin_service, "now_local", lambda: LATE)
    monkeypatch.setattr(day_plan, "now_local", lambda: LATE)


async def test_the_recap_pulls_the_days_steps_first(db_session, session_factory, monkeypatch):
    """The scheduled pulls can be most of an hour old at 23:45. The recap fetches
    today's summary itself, quotes it, and journals the count it quoted."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()
    _patch_pulse(monkeypatch, {"totalSteps": 9300, "lastSyncTimestampGMT": _gmt(LATE)})

    await day_plan.evening_job(session_factory)

    assert _PulseClient.calls == [DAY]
    recap = notifier.sent[0]["text"]
    assert "9300 шагов" in recap
    assert "синкались" not in recap  # the watch uploaded minutes ago
    row = await delivery.find_by_key(db_session, day_plan.dedupe_key(DAY))
    assert row.payload["meta"] == {"steps": 9300}
    # Last night survived the partial payload.
    assert (await garmin_service.get_daily(db_session, DAY)).sleep_score == 80


async def test_the_recap_says_when_the_watch_stopped_uploading(
    db_session, session_factory, monkeypatch
):
    """Garmin only knows what the phone handed over. A day that stopped counting
    at 19:40 says so instead of passing 3466 off as the total."""
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)
    _patch_pulse(monkeypatch, {
        "totalSteps": 3466,
        "lastSyncTimestampGMT": _gmt(LATE.replace(hour=19, minute=40)),
    })

    await day_plan.evening_job(session_factory)

    assert "⚠️ часы синкались в 19:40 — итог неполный" in notifier.sent[0]["text"]


def test_a_sync_from_another_day_carries_its_date():
    garmin = type("Row", (), {
        "steps": 120, "active_calories": None,
        "intensity_minutes_moderate": None, "intensity_minutes_vigorous": None,
    })()
    line = day_plan.summary_line(
        garmin, synced_at=LATE - timedelta(days=1, hours=2), now=LATE
    )
    assert "синкались в 25.07 21:45" in line


async def test_a_replayed_evening_does_not_pull_again(db_session, session_factory, monkeypatch):
    notifier = FakeNotifier()
    _patch_evening(monkeypatch, notifier)
    _patch_pulse(monkeypatch, {"totalSteps": 9300})

    await day_plan.evening_job(session_factory)
    await day_plan.evening_job(session_factory)

    assert _PulseClient.calls == [DAY]


# ── Taps ──────────────────────────────────────────────────────────────────────
async def test_tap_overwrites_the_answer_and_keeps_the_guess(db_session):
    await day_plan.record_plan(db_session, TOMORROW, {"where": "office", "gym": False})

    await day_plan.record_answer(db_session, TOMORROW, "gym", True)
    await day_plan.record_answer(db_session, TOMORROW, "load", "heavy")
    await db_session.commit()

    row = await signals_service.get_day_context(db_session, TOMORROW)
    assert row.answers == {"gym": True, "load": "heavy"}
    assert row.planned == {"where": "office", "gym": False}
    assert row.source == Source.MANUAL.value


async def test_a_tap_on_an_unasked_day_still_records_what_the_template_thought(
    db_session,
):
    """The brief's exception buttons can be the first thing ever tapped for a day."""
    await day_plan.record_answer(db_session, DAY, "where", "remote")
    await db_session.commit()

    row = await signals_service.get_day_context(db_session, DAY)
    assert row.answers == {"where": "remote"}
    assert row.planned == day_plan.DEFAULT_TEMPLATE["sun"]


async def test_exception_buttons_offer_every_other_answer(db_session):
    buttons = day_plan.exception_buttons({"where": "office", "gym": False, "load": "normal"}, DAY)
    payloads = dict((payload, label) for label, payload in buttons)

    assert f"ctx:{DAY.isoformat()}:where:remote" in payloads
    assert f"ctx:{DAY.isoformat()}:where:off" in payloads
    assert f"ctx:{DAY.isoformat()}:gym:1" in payloads
    # Never a button for what he is already down as doing.
    assert f"ctx:{DAY.isoformat()}:where:office" not in payloads
    # And never the recap question: a plan keyboard is about a day ahead, and how
    # heavy that day turns out is not something he can answer in advance.
    assert not [p for p in payloads if ":load:" in p]


async def test_an_unanswered_day_type_offers_all_three_options(db_session):
    """No weekday predicts how heavy a day is, so there is no "other" to offer —
    every option has to be a button or the question can never be answered."""
    buttons = day_plan.exception_buttons(
        {"where": "office", "gym": False}, DAY, (), day_plan.RECAP_QUESTIONS
    )
    payloads = {payload for _, payload in buttons}

    assert payloads == {f"ctx:{DAY.isoformat()}:load:{v}" for v in ("light", "normal", "heavy")}


def test_an_unanswered_question_is_left_unsaid():
    """Falling back to the default would print "обычный день" for a day nobody
    described — a guess read out as fact."""
    assert day_plan.describe({"where": "remote", "gym": False}) == "удалёнка · без зала"
    assert day_plan.describe({"where": "off"}) == "выходной"


# ── The template ──────────────────────────────────────────────────────────────
async def test_template_is_stored_per_weekday_and_sanitized(db_session):
    await day_plan.set_week_template(
        db_session,
        {"sun": {"where": "remote", "gym": True, "нечто": 1}, "junk": {}},
    )
    await db_session.commit()

    template = await day_plan.get_week_template(db_session)
    assert set(template) == set(day_plan.WEEKDAYS)
    assert template["sun"] == {"where": "remote", "gym": True}
    assert template["mon"] == day_plan.DEFAULT_DAY
    assert day_plan.guess_for(template, DAY) == template["sun"]  # DAY is a Sunday


async def test_the_template_never_carries_the_day_type(db_session):
    """A weekday cannot know how heavy a day will be, so it is not offered in
    Settings — and a hand-edited row that smuggles one in gets dropped."""
    assert "load" not in day_plan.DEFAULT_DAY
    assert "load" not in {q.key for q in day_plan.TEMPLATE_QUESTIONS}

    await day_plan.set_week_template(db_session, {"sun": {"load": "heavy"}})
    await db_session.commit()

    assert "load" not in (await day_plan.get_week_template(db_session))["sun"]


async def test_a_day_off_is_a_kind_of_day_and_the_weekend_defaults_to_it(db_session):
    assert day_plan.DEFAULT_TEMPLATE["sat"]["where"] == "off"
    assert day_plan.DEFAULT_TEMPLATE["sun"]["where"] == "off"
    assert day_plan.DEFAULT_TEMPLATE["mon"]["where"] == "office"

    await day_plan.set_week_template(db_session, {"mon": {"where": "off"}})
    await db_session.commit()

    template = await day_plan.get_week_template(db_session)
    assert template["mon"]["where"] == "off"
    assert day_plan.describe(template["mon"]).startswith("выходной")


async def test_a_broken_template_row_does_not_take_the_evening_block_down(db_session):
    """Hand-editable JSON is a trust boundary: garbage degrades to the default."""
    db_session.add(AppSetting(key=day_plan.SETTINGS_KEY, value="что-то не то"))
    await db_session.commit()

    assert await day_plan.get_week_template(db_session) == day_plan.DEFAULT_TEMPLATE


async def test_an_out_of_registry_value_falls_back_instead_of_reaching_the_message(
    db_session,
):
    await day_plan.set_week_template(db_session, {"sun": {"where": "на луне"}})
    await db_session.commit()

    template = await day_plan.get_week_template(db_session)
    assert template["sun"]["where"] == "off"  # Sunday's default, not the garbage


# ── The brief ─────────────────────────────────────────────────────────────────
async def _seed_brief_day(db_session):
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()


async def test_brief_prefers_his_answer_to_the_template(db_session, monkeypatch):
    """And only for the question he actually answered: one tap must not silently
    cancel the rest of the guess he was correcting."""
    await _seed_brief_day(db_session)
    await day_plan.set_week_template(db_session, {"sun": {"where": "remote", "gym": False}})
    await day_plan.record_answer(db_session, DAY, "gym", True)
    await db_session.commit()

    llm = FakeLLM()
    row = await brief.generate_brief(db_session, llm, on_date=DAY)
    await db_session.commit()

    assert "Сегодня: удалёнка · зал" in row.content
    assert "по шаблону" not in row.content
    # …and the model is told this is his answer, not a guess.
    assert '"source": "manual"' in llm.calls[0]["prompt"]

    # B6: answering one question must not retract the other. The keyboard keeps
    # offering "где" and stops offering "зал" — and never asks how heavy today
    # will be, which is the evening's question about the day it can already see.
    payloads = {p for _, p in day_plan.buttons_from_context(row.context_json["day"], DAY)}
    assert not [p for p in payloads if ":gym:" in p]
    assert f"ctx:{DAY.isoformat()}:where:office" in payloads
    assert not [p for p in payloads if ":load:" in p]


async def test_brief_falls_back_to_the_template_and_offers_the_exceptions(
    db_session, session_factory, monkeypatch
):
    notifier = FakeNotifier()
    from vitals.integrations import llm_client
    from vitals.services.proactive import channels

    async def _no_sync(*a, **kw):
        return None

    monkeypatch.setattr(garmin_service, "sync_job", _no_sync)
    monkeypatch.setattr(channels, "build_notifier", lambda *a, **kw: notifier)
    monkeypatch.setattr(llm_client, "LLMClient", lambda *a, **kw: FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    monkeypatch.setattr(day_plan, "today_local", lambda: DAY)

    await day_plan.set_week_template(db_session, {"sun": {"where": "remote"}})
    await _seed_brief_day(db_session)

    await brief.brief_job(session_factory)

    message = notifier.sent[0]
    assert "Сегодня по шаблону: удалёнка · без зала" in message["text"]
    assert message["buttons"], "an unanswered day has to be correctable in one tap"
    for _, payload in message["buttons"]:
        assert payload.startswith(f"{inbound.CB_CONTEXT}{DAY.isoformat()}:")


# ── The reply the evening block invites ───────────────────────────────────────
async def test_a_reply_to_the_evening_block_is_captured_not_answered(
    db_session, monkeypatch
):
    """«Как день?» is a question *to him* — his reply is data, and routing it to the
    Q&A path would answer it instead of recording it."""
    notifier = FakeNotifier()
    sent = await delivery.send(
        db_session, notifier, text="Как день?", category=delivery.CATEGORY_EVENING
    )

    async def _never(*a, **kw):
        raise AssertionError("the evening answer must not go to the Q&A path")

    monkeypatch.setattr(inbound, "answer_reply", _never)

    async def _parse(text):
        return [{"kind": "state", "key": "fatigue", "value_num": 4, "note": text}]

    await inbound.handle_text(
        db_session,
        "устал как собака",
        notifier=notifier,
        message_id=51,
        reply_to_message_id=sent.external_id,
        parse=_parse,
        on_date=DAY,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(Signal))).scalars().all()
    assert [r.key for r in rows] == ["fatigue"]
