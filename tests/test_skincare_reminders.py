"""The skincare checklist in Telegram.

The promises that matter: the checklist always goes out at its time — a spent
daily budget or quiet hours must not eat it; a reminder after midnight is about
the evening before, not a new day; and a tap under it lands on the day it was
sent for and redraws the message from what is stored, so the chat and the app
never disagree about what was done.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from vitals.models.proactive import Notification
from vitals.services import modules_service, skincare_service
from vitals.services.proactive import delivery, inbound, prefs
from vitals.services.proactive import skincare as reminders

pytestmark = pytest.mark.usefixtures("signals_module_on")

WED = datetime(2026, 10, 21, 22, 30)  # an evening, weekday 3 in the catalog


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.toasts: list[str] = []

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append({"text": text, "buttons": list(buttons or [])})
        return str(900 + len(self.sent))

    async def answer_callback(self, callback_id, text="") -> None:
        self.toasts.append(text)

    async def edit(self, message_id, text, *, buttons=None) -> None:
        self.edits.append({"id": message_id, "text": text, "buttons": list(buttons or [])})


@pytest.fixture
async def skincare_on(db_session):
    await modules_service.set_module_enabled(db_session, key="skincare", enabled=True)
    await db_session.commit()


async def _product(db_session, name, *, time="evening", flag=None, **fields):
    row = await skincare_service.add_product(
        db_session, name=name, type="test", default_time=time, schedule_days=[3],
        active_flag=flag, **fields,
    )
    await db_session.commit()
    return row


def _labels(message: dict) -> list[str]:
    return [label for label, _ in message["buttons"]]


def _tap(data: str, message_id: int = 901, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {"id": f"cb{update_id}", "data": data, "message": {"message_id": message_id}},
    }


# ── Sending ──────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("skincare_on")
async def test_evening_checklist_lists_the_plan_with_a_button_each(db_session):
    a = await _product(db_session, "Дифферин")
    b = await _product(db_session, "Крем")
    await _product(db_session, "SPF", time="morning")
    notifier = FakeNotifier()

    row = await reminders.send_slot(db_session, notifier, "evening", now=WED)

    assert row is not None and row.category == delivery.CATEGORY_SKINCARE
    msg = notifier.sent[0]
    # The checklist is the keyboard; the text doesn't repeat it.
    assert msg["text"] == "🌙 Вечерний уход · ср 21.10"
    assert _labels(msg) == ["⬜ Дифферин", "⬜ Крем", reminders.ALL_BUTTON]
    payloads = [p for _, p in msg["buttons"]]
    assert payloads == [
        f"sk:2026-10-21:evening:{a.id}",
        f"sk:2026-10-21:evening:{b.id}",
        "sk:2026-10-21:evening:all",
    ]


@pytest.mark.usefixtures("skincare_on")
async def test_it_spends_no_budget_and_ignores_quiet_hours(db_session):
    """A budget of one, already spent by a nudge, at 03:00 inside quiet hours:
    the checklist still goes out."""
    await prefs.set_prefs(db_session, {"daily_budget": 1, "quiet_start": "02:00", "quiet_end": "10:00"})
    await _product(db_session, "Крем")
    night = WED.replace(hour=3) + timedelta(days=1)  # Wednesday's night, Thursday's date
    db_session.add(
        Notification(sent_at=night, category=delivery.CATEGORY_NUDGE, channel="telegram", payload={})
    )
    await db_session.commit()
    notifier = FakeNotifier()

    assert await reminders.send_slot(db_session, notifier, "evening", now=night) is not None
    assert await delivery.sent_today(db_session, on_date=night.date()) == 1  # still just the nudge


@pytest.mark.usefixtures("skincare_on")
async def test_once_per_slot_per_day(db_session):
    await _product(db_session, "Крем")
    notifier = FakeNotifier()
    await reminders.send_slot(db_session, notifier, "evening", now=WED)
    await reminders.send_slot(db_session, notifier, "evening", now=WED + timedelta(minutes=5))
    assert len(notifier.sent) == 1


@pytest.mark.usefixtures("skincare_on")
async def test_silent_when_nothing_is_planned_or_all_is_done(db_session):
    notifier = FakeNotifier()
    assert await reminders.send_slot(db_session, notifier, "evening", now=WED) is None

    p = await _product(db_session, "Крем")
    await skincare_service.set_check(
        db_session, on_date=WED.date(), product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()
    assert await reminders.send_slot(db_session, notifier, "evening", now=WED) is None
    assert notifier.sent == []


async def test_silent_with_the_module_off(db_session):
    await _product(db_session, "Крем")
    notifier = FakeNotifier()
    assert await reminders.send_slot(db_session, notifier, "evening", now=WED) is None


@pytest.mark.usefixtures("skincare_on")
async def test_silent_with_its_toggle_off(db_session):
    await _product(db_session, "Крем")
    await prefs.set_prefs(db_session, {"nudges": {prefs.CATEGORY_SKINCARE: False}})
    await db_session.commit()
    notifier = FakeNotifier()
    assert await reminders.send_slot(db_session, notifier, "evening", now=WED) is None


# ── Taps ─────────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("skincare_on")
async def test_a_tap_ticks_and_redraws_and_a_second_tap_unticks(db_session):
    a = await _product(db_session, "Дифферин", flag="retinoid")
    await _product(db_session, "Крем")
    notifier = FakeNotifier()
    data = f"sk:2026-10-21:evening:{a.id}"

    await inbound.handle_update(db_session, _tap(data), notifier=notifier)
    await db_session.commit()

    assert notifier.toasts == ["Отмечено"]
    edit = notifier.edits[-1]
    assert edit["id"] == "901"
    assert _labels(edit) == ["✅ Дифферин", "⬜ Крем"]
    assert (await skincare_service.get_log(db_session, WED.date())).retinoid is True

    await inbound.handle_update(db_session, _tap(data, update_id=2), notifier=notifier)
    await db_session.commit()
    assert notifier.toasts[-1] == "Снял отметку"
    assert "⬜ Дифферин" in _labels(notifier.edits[-1])


@pytest.mark.usefixtures("skincare_on")
async def test_all_done_ticks_the_rest_and_says_so(db_session):
    await _product(db_session, "A")
    await _product(db_session, "B")
    notifier = FakeNotifier()

    await inbound.handle_update(db_session, _tap("sk:2026-10-21:evening:all"), notifier=notifier)
    await db_session.commit()

    # Everything ticked: the message folds into its header, the keyboard goes.
    edit = notifier.edits[-1]
    assert edit["text"] == f"🌙 Вечерний уход · ср 21.10 {reminders.DONE_SUFFIX}"
    assert edit["buttons"] == []
    plan = await skincare_service.plan_for(db_session, WED.date())
    assert all(i["done"] for i in plan["evening"])


@pytest.mark.usefixtures("skincare_on")
async def test_a_conflicting_tap_is_recorded_and_the_toast_names_the_rule(db_session):
    """What was done was done: the chat records it and warns, it doesn't refuse."""
    from vitals.models.conflict_rule import ConflictRule

    db_session.add(
        ConflictRule(
            rule_type="hard_block",
            domain_a="skincare",
            condition_a={"retinoid": True},
            domain_b="skincare",
            condition_b={"peel": True},
            severity="block",
            message="Ретиноид и пилинг в один вечер.",
            active=True,
        )
    )
    ret = await _product(db_session, "Дифферин", flag="retinoid")
    peel = await _product(db_session, "Пилинг", flag="peel")
    notifier = FakeNotifier()

    await inbound.handle_update(db_session, _tap(f"sk:2026-10-21:evening:{ret.id}"), notifier=notifier)
    await inbound.handle_update(
        db_session, _tap(f"sk:2026-10-21:evening:{peel.id}", update_id=2), notifier=notifier
    )
    await db_session.commit()

    assert "Ретиноид и пилинг" in notifier.toasts[-1]
    log = await skincare_service.get_log(db_session, WED.date())
    assert log.retinoid is True and log.peel is True


@pytest.mark.usefixtures("skincare_on")
async def test_a_tap_on_a_deleted_product_does_nothing(db_session):
    notifier = FakeNotifier()
    await inbound.handle_update(db_session, _tap("sk:2026-10-21:evening:999"), notifier=notifier)
    await inbound.handle_update(db_session, _tap("sk:garbage", update_id=2), notifier=notifier)
    assert notifier.edits == []
    assert notifier.toasts == ["", ""]


@pytest.mark.usefixtures("skincare_on")
async def test_a_tick_in_the_app_redraws_the_sent_message(db_session):
    p = await _product(db_session, "Крем")
    await _product(db_session, "Сыворотка")
    notifier = FakeNotifier()
    await reminders.send_slot(db_session, notifier, "evening", now=WED)
    await skincare_service.set_check(
        db_session, on_date=WED.date(), product_id=p.id, slot="evening", done=True
    )
    await db_session.commit()

    await reminders.sync_sent(db_session, notifier, WED.date(), "evening")

    journal = (await db_session.execute(select(Notification))).scalars().all()
    assert notifier.edits[-1]["id"] == journal[0].external_id
    assert "✅ Крем" in _labels(notifier.edits[-1])


async def test_sync_without_a_sent_message_is_a_no_op(db_session):
    notifier = FakeNotifier()
    await reminders.sync_sent(db_session, notifier, WED.date(), "evening")
    assert notifier.edits == []


def test_parse_rejects_what_it_cannot_apply():
    assert reminders.parse("sk:2026-10-21:noon:1") is None
    assert reminders.parse("sk:2026-10-21:evening:x") is None
    assert reminders.parse("sk:not-a-date:evening:1") is None
    assert reminders.parse("sk:2026-10-21:evening:all")[2] is None


# ── The routine day ──────────────────────────────────────────────────────────
@pytest.mark.usefixtures("skincare_on")
async def test_after_midnight_the_evening_reminder_is_about_the_evening_before(db_session):
    """01:00 on Thursday is still Wednesday's evening: Wednesday's products, a
    Wednesday header, Wednesday in every button — and a tap lands there."""
    p = await _product(db_session, "Дифферин", flag="retinoid")
    notifier = FakeNotifier()
    one_am = datetime(2026, 10, 22, 1, 0)

    await reminders.send_slot(db_session, notifier, "evening", now=one_am)

    msg = notifier.sent[0]
    assert msg["text"].startswith("🌙 Вечерний уход · ср 21.10")
    assert msg["buttons"][0][1] == f"sk:2026-10-21:evening:{p.id}"


@pytest.mark.usefixtures("skincare_on")
async def test_the_day_end_is_the_owners_setting(db_session):
    """With the day ending at midnight, 01:00 Thursday is Thursday — and the
    Wednesday-only product isn't on it."""
    await prefs.set_prefs(db_session, {"day_end": "00:00"})
    await _product(db_session, "Дифферин")
    notifier = FakeNotifier()

    assert await reminders.send_slot(db_session, notifier, "evening", now=datetime(2026, 10, 22, 1, 0)) is None


# ── How, in what order, and the day's note ───────────────────────────────────
@pytest.mark.usefixtures("skincare_on")
async def test_the_message_says_how_to_apply_what_is_still_open(db_session):
    await _product(db_session, "Крем", usage_instructions="тонко", usage_evening="толстым слоем", step=3)
    ret = await _product(db_session, "Дифферин", usage_instructions="горошина на сухую кожу", step=2)
    await _product(db_session, "Умывалка", step=1)
    notifier = FakeNotifier()

    await reminders.send_slot(db_session, notifier, "evening", now=WED)

    msg = notifier.sent[0]
    # Buttons in the order of application; the evening's own instructions win.
    assert _labels(msg)[:3] == ["⬜ Умывалка", "⬜ Дифферин", "⬜ Крем"]
    assert msg["text"].splitlines() == [
        "🌙 Вечерний уход · ср 21.10",
        "",
        "Дифферин — горошина на сухую кожу",
        "Крем — толстым слоем",
    ]

    # Once applied, how to apply it is no longer worth a line.
    await inbound.handle_update(
        db_session, _tap(f"sk:2026-10-21:evening:{ret.id}"), notifier=notifier
    )
    assert "Дифферин —" not in notifier.edits[-1]["text"]


@pytest.mark.usefixtures("skincare_on")
async def test_the_days_note_heads_the_message_and_a_late_note_redraws_it(db_session):
    await _product(db_session, "Дифферин")
    await _product(db_session, "Крем")
    notifier = FakeNotifier()
    await reminders.send_slot(db_session, notifier, "evening", now=WED)
    assert reminders.NOTE_MARK not in notifier.sent[0]["text"]

    await skincare_service.set_note(
        db_session, on_date=WED.date(), slot="evening", text="Щёки раздражены — ретиноид только на лоб"
    )
    await db_session.commit()
    await reminders.sync_sent(db_session, notifier, WED.date(), "evening")

    assert notifier.edits[-1]["text"].splitlines()[:2] == [
        "🌙 Вечерний уход · ср 21.10",
        "💬 Щёки раздражены — ретиноид только на лоб",
    ]
