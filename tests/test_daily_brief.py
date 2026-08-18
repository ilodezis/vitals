"""The morning brief: the numbers, the fallback, and the silence.

Each of these guards something that fails quietly. A header that drifts from the
database is worse than no brief at all; a dead model that takes the whole message
down with it turns the one proactive feature into nothing; and a brief that keeps
arriving with "нет данных", or that carries the hormone protocol into Telegram,
is a product decision reversed by accident.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from vitals.enums import DigestKind, Severity, Source
from vitals.models.milestones import WeeklyDigest
from vitals.models.proactive import Notification
from vitals.models.system_alert import SystemAlert
from vitals.services import (
    digest_service,
    garmin_service,
    nutrition_service,
    weight_service,
)
from vitals.services.proactive import brief, compose, day_plan, delivery

# The bot only speaks when the ``signals`` module is on — the same switch the
# owner flips in Settings, and it defaults off.
pytestmark = pytest.mark.usefixtures("all_modules_on")

DAY = date(2026, 7, 26)

# One day of Garmin as it arrives from the API, with exactly the five numbers the
# header is specified to print.
GARMIN_RAW = {
    "summary": {"restingHeartRate": 52, "bodyBatteryHighestValue": 84},
    "sleep": {"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}},
    "hrv": {"hrvSummary": {"lastNightAvg": 61}},
}


class FakeLLM:
    """Records what it was asked; answers with one paragraph."""

    digest_model = "fake/digest"
    brief_model = "fake/brief"

    def __init__(self, answer="Восстановление в норме, можно грузиться."):
        self.calls: list[dict] = []
        self._answer = answer

    async def complete_text(self, prompt, *, model=None, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        return self._answer


class BoomLLM:
    """The upstream is down / out of balance / has no key."""

    digest_model = "fake/digest"
    brief_model = "fake/brief"

    async def complete_text(self, *a, **kw):
        raise RuntimeError("openrouter is having a bad day")


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append({"text": text, "buttons": buttons})
        return str(900 + len(self.sent))

    async def answer_callback(self, callback_id, text="") -> None:
        pass


async def _seed_day(db_session, *, on_date=DAY, weight_kg=88.0):
    await garmin_service.ingest_daily(db_session, on_date, GARMIN_RAW)
    if weight_kg is not None:
        await weight_service.log_weight(db_session, on_date=on_date, weight_kg=weight_kg)
    await db_session.commit()


# ── The header ────────────────────────────────────────────────────────────────
async def test_header_numbers_match_the_database(db_session):
    """Every number in the header is printed by code from the stored row — the
    model is never in a position to get one wrong."""
    await _seed_day(db_session)

    row = await brief.generate_brief(db_session, FakeLLM(), on_date=DAY)
    await db_session.commit()

    stored = await garmin_service.latest_daily(db_session, before_or_on=DAY)
    assert f"Сон {stored.sleep_score}" in row.content
    assert f"HRV {int(stored.hrv_avg)}" in row.content
    assert f"Пульс покоя {stored.resting_hr}" in row.content
    assert f"Body Battery {stored.body_battery_high}" in row.content
    assert "Вес 88 кг" in row.content
    assert "Восстановление в норме" in row.content


async def test_noisy_weight_never_prints_a_bare_trend(db_session):
    """A noise marker means the scale is lying in a known direction. The trend is
    the one header number that can mislead while being technically correct."""
    for i in range(8):
        day = DAY - timedelta(days=7 - i)
        await weight_service.log_weight(db_session, on_date=day, weight_kg=90.0 - i * 0.2)
    await weight_service.add_noise_marker(
        db_session, start_date=DAY - timedelta(days=3), reason="загрузка креатином",
        direction="up",
    )
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()

    ctx = await brief.build_context(db_session, on_date=DAY)
    text = compose.render(compose.header_blocks(ctx))
    if "тренд" in text:
        assert "зашумлён" in text
        assert "креатином" in text


async def test_the_header_carries_his_own_norm_only_when_today_is_off_it(db_session):
    """A single day of absolutes is the same line every morning, and whether 78 is
    good is a comparison. Printed by code from his own fortnight — and printed
    only when it says something, so the parenthesis stays worth reading."""
    for i in range(1, 11):  # ten days of a steady sleep score of 85, RHR 52
        day = DAY - timedelta(days=i)
        await garmin_service.ingest_daily(db_session, day, {
            "summary": {"restingHeartRate": 52, "bodyBatteryHighestValue": 84},
            "sleep": {"dailySleepDTO": {"sleepScores": {"overall": {"value": 85}}}},
            "hrv": {"hrvSummary": {"lastNightAvg": 61}},
        })
    await _seed_day(db_session)  # today: sleep 80, RHR 52 — same as every other day

    ctx = await brief.build_context(db_session, on_date=DAY)
    assert ctx["garmin"]["baseline"]["sleep_score"] == 85
    # Today's own row must not be averaged into the yardstick it is judged by.
    assert ctx["garmin"]["baseline"]["resting_hr"] == 52

    text = compose.render(compose.header_blocks(ctx))
    assert "Сон 80 (норма 85)" in text          # ~6% off — worth saying
    assert "Пульс покоя 52 ·" in text or text.rstrip().endswith("Пульс покоя 52")
    assert "Пульс покоя 52 (" not in text       # on the norm — say nothing


async def test_no_norm_until_there_is_enough_history(db_session):
    """Two nights is not a baseline. Left unguarded the model gets a "norm" made
    of noise and calls a просадка against it — the invented comparison this whole
    block exists to stop."""
    await garmin_service.ingest_daily(db_session, DAY - timedelta(days=1), GARMIN_RAW)
    await _seed_day(db_session)

    ctx = await brief.build_context(db_session, on_date=DAY)
    assert ctx["garmin"]["baseline"] is None
    assert "норма" not in compose.render(compose.header_blocks(ctx))


async def test_the_brief_sees_yesterdays_signals(db_session):
    """"Кофе в 22" is yesterday's row and this morning's HRV is what it explains.
    A one-day window would cut every exposure away from the number it caused."""
    from vitals.services import signals_service

    await signals_service.create_signals(
        db_session,
        items=[{"kind": "exposure", "key": "caffeine_late", "at_time": "22:00"}],
        on_date=DAY - timedelta(days=1),
    )
    await signals_service.create_signals(
        db_session,
        items=[{"kind": "state", "key": "sleepiness", "value_num": 5}],
        on_date=DAY,
    )
    # Two days back is outside the window: the brief is about this morning.
    await signals_service.create_signals(
        db_session,
        items=[{"kind": "symptom", "key": "headache", "value_num": 3}],
        on_date=DAY - timedelta(days=2),
    )
    await db_session.commit()

    ctx = await brief.build_context(db_session, on_date=DAY)

    assert [s["key"] for s in ctx["signals"]] == ["caffeine_late", "sleepiness"]
    assert ctx["signals"][0]["at_time"] == "22:00"


async def test_the_brief_uses_closed_yesterday_nutrition_not_todays_breakfast(
    db_session,
):
    for name, calories, protein in (
        ("Breakfast", 800.0, 80.0),
        ("Dinner", 850.0, 80.0),
    ):
        await nutrition_service.log_meal(
            db_session,
            on_date=DAY - timedelta(days=1),
            name=name,
            calories=calories,
            protein_g=protein,
        )
    for name, calories, protein in (
        ("Oats", 250.0, 20.0),
        ("Protein", 170.0, 15.0),
    ):
        await nutrition_service.log_meal(
            db_session,
            on_date=DAY,
            name=name,
            calories=calories,
            protein_g=protein,
        )
    await _seed_day(db_session)

    ctx = await brief.build_context(db_session, on_date=DAY)

    assert ctx["nutrition"]["date"] == (DAY - timedelta(days=1)).isoformat()
    assert ctx["nutrition"]["calendar_day_closed"] is True
    assert ctx["nutrition"]["entries_logged"] == 2
    assert ctx["nutrition"]["totals"] == {
        "calories": 1650.0,
        "protein_g": 160.0,
        "fat_g": None,
        "carbs_g": None,
    }
    assert ctx["nutrition"]["goals"]["protein_target_g"] == 150.0
    prompt = brief.build_prompt(ctx)
    assert '"avg_calories_per_day": 420' not in prompt
    assert '"calories": 1650.0' in prompt
    assert "не переноси значения между датами" in prompt
    assert "Текущего утра в JSON нет" in brief.BRIEF_SYSTEM


# ── The fallback ──────────────────────────────────────────────────────────────
async def test_brief_survives_a_dead_model(db_session):
    """No narrative is a missing block, not a missing brief."""
    await _seed_day(db_session)

    row = await brief.generate_brief(db_session, BoomLLM(), on_date=DAY)
    await db_session.commit()

    assert row is not None
    assert "Сон 80" in row.content
    assert row.model is None  # nothing was written by a model


async def test_narrative_uses_the_brief_model_and_is_told_to_be_short(db_session):
    await _seed_day(db_session)
    llm = FakeLLM()

    row = await brief.generate_brief(db_session, llm, on_date=DAY)
    await db_session.commit()

    assert llm.calls[0]["model"] == "fake/brief"
    assert "2-3 предложения" in llm.calls[0]["system"]
    assert row.model == "fake/brief"


# ── Storage ───────────────────────────────────────────────────────────────────
async def test_brief_is_stored_as_its_own_kind(db_session):
    """One table, two kinds — and a brief must never surface where a weekly
    digest is expected (the /reports card, the MCP resource)."""
    await _seed_day(db_session)

    row = await brief.generate_brief(db_session, FakeLLM(), on_date=DAY)
    await db_session.commit()

    assert row.kind == DigestKind.DAILY_BRIEF.value
    assert await digest_service.latest_digest(db_session) is None
    assert (
        await digest_service.latest_digest(db_session, kind=DigestKind.DAILY_BRIEF.value)
    ).id == row.id
    assert await digest_service.list_digests(db_session) == []


async def test_protocol_never_reaches_the_brief(db_session):
    """No doses, no compounds, no injection schedule, no supplements — not in
    the stored context and not in the prompt. The weekly digest still sees it all."""
    from vitals.services import glp1_service, supplements_service

    await glp1_service.add_dose_phase(
        db_session, start_date=DAY - timedelta(days=30), drug="semaglutide", dose_mg=1.0
    )
    await supplements_service.add_supplement(
        db_session, name="Ашваганда", key="ashwagandha", active=True
    )
    await _seed_day(db_session)

    llm = FakeLLM()
    row = await brief.generate_brief(db_session, llm, on_date=DAY)
    await db_session.commit()

    for key in compose.PROTOCOL_KEYS:
        assert key not in row.context_json
    prompt = llm.calls[0]["prompt"]
    assert "semaglutide" not in prompt
    assert "Ашваганда" not in prompt

    # …and the weekly digest is untouched by any of this.
    full = await digest_service.assemble_context(db_session, on_date=DAY)
    assert full["glp1"]["drug"] == "semaglutide"
    assert full["supplements"][0]["name"] == "Ашваганда"


def test_protocol_is_removed_from_secondary_context_surfaces():
    stripped = compose.strip_protocol(
        {
            "glp1": {"drug": "private"},
            "hrt": {"cycle": "private"},
            "coverage": {"glp1": {}, "hrt": {}, "weight": {}},
            "alerts": [
                {"domain": "hrt", "message": "private"},
                {"domain": "labs", "message": "visible"},
            ],
            "timeline": [
                {"domain": "glp1", "title": "private"},
                {"domain": "timeline", "title": "visible"},
            ],
            "milestones": [
                {"domain": "hrt", "name": "private"},
                {"domain": "weight", "name": "visible"},
            ],
        }
    )

    assert set(stripped["coverage"]) == {"weight"}
    assert stripped["alerts"] == [{"domain": "labs", "message": "visible"}]
    assert stripped["timeline"] == [
        {"domain": "timeline", "title": "visible"}
    ]
    assert stripped["milestones"] == [
        {"domain": "weight", "name": "visible"}
    ]


# ── The night that hasn't ended yet ───────────────────────────────────────────
# Today's row as it looks while he is still asleep: Garmin fills the day-so-far
# numbers, and the sleep DTO — score, duration, sleep end — does not exist until
# the night is closed. Body Battery here is the overnight *low*, not a peak.
GARMIN_MID_NIGHT = {
    "summary": {"restingHeartRate": 68, "bodyBatteryHighestValue": 24},
}


async def test_a_running_night_never_reaches_the_brief(db_session):
    """The prod bug: the 11:00 brief caught him asleep, read Body Battery 24 and
    resting HR 68 off a night still in progress, called recovery wrecked and told
    him to skip the gym — then stored all of it, where the weekly digest reads it
    back as what that morning actually was."""
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_MID_NIGHT)
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await db_session.commit()

    row = await brief.generate_brief(db_session, FakeLLM(), on_date=DAY)
    await db_session.commit()

    assert "Пульс покоя" not in row.content
    assert "Body Battery" not in row.content
    assert compose.LINE_NIGHT_PENDING in row.content
    assert "Вес 88 кг" in row.content  # what *is* known still goes out
    # And the stored context says why, so nothing downstream fills the gap in.
    assert row.context_json["garmin"]["night_pending"] is True
    assert row.context_json["garmin"]["resting_hr"] is None
    assert row.context_json["garmin"]["advice"] is None


async def test_a_scored_night_is_untouched(db_session):
    """The guard must not fire on a normal morning — that would delete the header."""
    await _seed_day(db_session)

    ctx = await brief.build_context(db_session, on_date=DAY)
    assert compose.night_pending(ctx, on_date=DAY) is False
    assert await brief.night_scored(db_session, DAY) is True


async def test_job_waits_for_the_night_instead_of_briefing_over_it(
    db_session, session_factory, monkeypatch
):
    """Inside the wait window an un-scored night costs nothing: no message, no
    stored brief, no model call, no empty-day alert — the next hourly fire looks
    again. Once the night lands, the brief goes out normally."""
    notifier = FakeNotifier()
    llm = FakeLLM()
    _patch_job(monkeypatch, notifier, llm)
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    monkeypatch.setattr(brief, "now_local", lambda: datetime(2026, 7, 26, 11, 0))
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_MID_NIGHT)
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await db_session.commit()

    await brief.brief_job(session_factory)

    assert notifier.sent == []
    assert (await db_session.execute(select(WeeklyDigest))).scalars().all() == []
    assert (await db_session.execute(select(SystemAlert))).scalars().all() == []
    assert llm.calls == []

    # He wakes up, the watch closes the night, the next fire an hour later sends.
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_RAW)
    await db_session.commit()

    await brief.brief_job(session_factory)

    assert len(notifier.sent) == 1
    assert "Сон 80" in notifier.sent[0]["text"]


async def test_job_stops_waiting_at_the_end_of_the_window(
    db_session, session_factory, monkeypatch
):
    """Waiting forever is its own failure: the last fire sends what there is,
    minus the numbers the night never produced."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    monkeypatch.setattr(
        brief, "now_local", lambda: datetime(2026, 7, 26, brief.last_attempt_hour(11), 0)
    )
    await garmin_service.ingest_daily(db_session, DAY, GARMIN_MID_NIGHT)
    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await db_session.commit()

    await brief.brief_job(session_factory)

    assert len(notifier.sent) == 1
    assert compose.LINE_NIGHT_PENDING in notifier.sent[0]["text"]
    assert "Body Battery" not in notifier.sent[0]["text"]


# ── The empty day ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, when",
    [
        (GARMIN_RAW, DAY + timedelta(days=5)),   # data exists, but it's stale
        ({"summary": {"totalSteps": 200}}, DAY),  # today's row carries no recovery
    ],
)
async def test_empty_day_builds_nothing(db_session, raw, when):
    await garmin_service.ingest_daily(db_session, DAY, raw)
    await db_session.commit()

    assert await brief.generate_brief(db_session, FakeLLM(), on_date=when) is None
    assert (await db_session.execute(select(WeeklyDigest))).scalars().all() == []


async def test_a_day_without_garmin_is_not_an_empty_day(db_session):
    """The watch on the charger used to silence the brief outright, even with
    the scale, the food log and his own words all filling normally."""
    from vitals.services import signals_service

    await weight_service.log_weight(db_session, on_date=DAY, weight_kg=88.0)
    await signals_service.create_signals(
        db_session,
        items=[{"kind": "state", "key": "fatigue", "value_num": 4}],
        on_date=DAY,
    )
    await db_session.commit()

    row = await brief.generate_brief(db_session, FakeLLM(), on_date=DAY)
    await db_session.commit()

    assert row is not None
    assert "Вес 88 кг" in row.content


async def test_a_weight_from_months_ago_does_not_keep_the_brief_talking(db_session):
    """The other edge: ``latest_kg`` is the newest weigh-in *ever*, so counting it
    without a date would mean one trip to the scale in March buys a brief every
    morning after — including mornings where nothing at all happened."""
    await weight_service.log_weight(db_session, on_date=DAY - timedelta(days=90), weight_kg=88.0)
    await db_session.commit()

    assert await brief.generate_brief(db_session, FakeLLM(), on_date=DAY) is None


async def test_job_stays_quiet_on_an_empty_day_and_says_so_in_the_web(
    db_session, session_factory, monkeypatch
):
    """Silence beats "нет данных" three mornings running — but the gap still
    has to be visible somewhere, so it becomes a passive info alert."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)

    await brief.brief_job(session_factory)

    assert notifier.sent == []
    assert (await db_session.execute(select(WeeklyDigest))).scalars().all() == []
    alert = (await db_session.execute(select(SystemAlert))).scalars().one()
    assert alert.alert_key == brief.EMPTY_DAY_ALERT_KEY
    assert alert.severity == Severity.INFO.value


async def test_job_sends_once_a_day_and_clears_the_empty_alert(
    db_session, session_factory, monkeypatch
):
    """A re-run of the 11:00 job is a no-op, not a second ping: Telegram retries
    and APScheduler misfires both replay a job."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)

    # An earlier empty morning left its alert behind.
    from vitals.services import alerts_service
    from vitals.enums import Domain

    await alerts_service.raise_alert(
        db_session, domain=Domain.SYSTEM.value, severity=Severity.INFO.value,
        message="stale", alert_key=brief.EMPTY_DAY_ALERT_KEY,
    )
    await _seed_day(db_session)

    await brief.brief_job(session_factory)
    await brief.brief_job(session_factory)

    assert len(notifier.sent) == 1
    assert "Сон 80" in notifier.sent[0]["text"]
    journal = (await db_session.execute(select(Notification))).scalars().all()
    assert [n.category for n in journal] == [delivery.CATEGORY_BRIEF]
    assert journal[0].dedupe_key == brief.dedupe_key(DAY)
    alert = (await db_session.execute(select(SystemAlert))).scalars().one()
    assert alert.resolved_at is not None


async def test_the_brief_says_what_its_buttons_are_for(
    db_session, session_factory, monkeypatch
):
    """Telegram renders the keyboard under the *whole* message, so four unlabelled
    taps ("зал", "лёгкий/обычный/тяжёлый день") arrive attached to nothing — and
    «тяжёлый день» is a question asked nowhere in the text at all. The stored
    brief keeps no hint: /reports shows it with no buttons underneath."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    await brief.brief_job(session_factory)

    sent = notifier.sent[0]
    assert sent["buttons"]
    assert sent["text"].endswith(day_plan.HINT_FIX)
    stored = (await db_session.execute(select(WeeklyDigest))).scalars().one()
    assert day_plan.HINT_FIX not in stored.content


async def test_a_brief_with_nothing_left_to_ask_carries_no_hint(
    db_session, session_factory, monkeypatch
):
    """The hint leaves with the last button — a line pointing at a keyboard that
    isn't there is worse than no line."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)
    for question in day_plan.QUESTIONS:
        await day_plan.record_answer(
            db_session, DAY, question.key, next(iter(question.labels))
        )
    await db_session.commit()

    await brief.brief_job(session_factory)

    assert notifier.sent[0]["buttons"] is None
    assert day_plan.HINT_FIX not in notifier.sent[0]["text"]


async def test_job_sends_the_brief_even_when_garmin_sync_explodes(
    db_session, session_factory, monkeypatch
):
    """B6 pulls Garmin first, but a failed pull is not a reason to go quiet — the
    brief goes out on whatever is already in the lake."""
    notifier = FakeNotifier()
    _patch_job(monkeypatch, notifier, FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)

    async def _boom(*a, **kw):
        raise RuntimeError("garmin said no")

    monkeypatch.setattr(garmin_service, "sync_job", _boom)
    await _seed_day(db_session)

    await brief.brief_job(session_factory)
    assert len(notifier.sent) == 1


def _patch_job(monkeypatch, notifier, llm):
    """Wire brief_job to a fake channel, a fake model and a no-op Garmin sync."""
    from vitals.integrations import llm_client
    from vitals.services.proactive import channels

    async def _no_sync(*a, **kw):
        return None

    monkeypatch.setattr(garmin_service, "sync_job", _no_sync)
    monkeypatch.setattr(channels, "build_notifier", lambda *a, **kw: notifier)
    monkeypatch.setattr(llm_client, "LLMClient", lambda *a, **kw: llm)


# ── The two buttons ───────────────────────────────────────────────────────────
async def test_build_button_shows_the_brief_and_sends_nothing(
    auth_client, db_session, monkeypatch
):
    from web.routers import reports as reports_router

    monkeypatch.setattr(reports_router, "LLMClient", lambda *a, **kw: FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    r = await auth_client.post("/reports/brief")
    assert r.status_code == 303
    assert r.headers["location"] == "/reports?brief=ok"

    rows = (await db_session.execute(select(WeeklyDigest))).scalars().all()
    assert [row.kind for row in rows] == [DigestKind.DAILY_BRIEF.value]
    assert rows[0].source == Source.MANUAL.value
    assert (await db_session.execute(select(Notification))).scalars().all() == []

    page = await auth_client.get("/reports")
    assert "Восстановление в норме" in page.text


async def test_test_send_goes_out_off_budget(auth_client, db_session, monkeypatch):
    """The point of this button is catching broken formatting, so it must send even
    after the day's budget is spent — and it isn't the bot talking first."""
    from vitals.utils.timeutils import now_local
    from web.main import app
    from web.routers import reports as reports_router
    from web.routers.telegram import get_notifier

    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    monkeypatch.setattr(reports_router, "LLMClient", lambda *a, **kw: FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    # Today's budget, fully spent (dated *now*, which is what the budget counts).
    for i in range(delivery.DAILY_BUDGET):
        db_session.add(
            Notification(
                sent_at=now_local(), category=delivery.CATEGORY_BRIEF,
                channel="telegram", dedupe_key=f"spent:{i}",
            )
        )
    await db_session.commit()
    assert await delivery.sent_today(db_session) >= delivery.DAILY_BUDGET

    r = await auth_client.post("/reports/brief/test")
    assert r.headers["location"] == "/reports?brief=sent"
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["text"].startswith("Сон 80")


async def test_test_send_is_not_duplicated_by_a_second_tap(auth_client, db_session, monkeypatch):
    """B2a: the test-send endpoint had no dedupe_key at all — the only delivery
    category with no dupe protection. A repeat call within the same day (a
    double-tap, or a retried request) must not fire a second Telegram message
    or pay for a second LLM call."""
    from web.main import app
    from web.routers import reports as reports_router
    from web.routers.telegram import get_notifier

    notifier = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: notifier
    monkeypatch.setattr(reports_router, "LLMClient", lambda *a, **kw: FakeLLM())
    monkeypatch.setattr(brief, "today_local", lambda: DAY)
    await _seed_day(db_session)

    r1 = await auth_client.post("/reports/brief/test")
    r2 = await auth_client.post("/reports/brief/test")

    assert r1.headers["location"] == "/reports?brief=sent"
    assert r2.headers["location"] == "/reports?brief=error"  # deduped, not a real error
    assert len(notifier.sent) == 1
    journal = (await db_session.execute(select(Notification))).scalars().all()
    assert [n.category for n in journal] == [delivery.CATEGORY_TEST]


async def test_test_send_without_a_channel_says_so(auth_client, db_session, monkeypatch):
    from web.main import app
    from web.routers.telegram import get_notifier

    app.dependency_overrides[get_notifier] = lambda: None
    r = await auth_client.post("/reports/brief/test")
    assert r.headers["location"] == "/reports?brief=no_channel"
