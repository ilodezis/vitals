"""Air-quality alerts: when they fire, when they stay quiet, and that each episode
speaks once.

``NOW`` is 15:00 local (Chisinau, UTC+3) — outside quiet hours (02:00-10:00).
``NIGHT`` is 03:00 local, inside them.
"""
from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from env_support import at, sample
from sqlalchemy import select

from vitals.i18n import current_lang
from vitals.models.proactive import Notification
from vitals.models.system_alert import SystemAlert
from vitals.services import alerts_service, modules_service
from vitals.services.environment import alerts
from vitals.services.environment import settings as env_settings
from vitals.services.proactive import delivery

pytestmark = pytest.mark.usefixtures("signals_module_on")

NOW = at("2026-10-05T12:00:00")
NIGHT = at("2026-10-05T00:00:00")  # 03:00 local

_boots = itertools.count(1)


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text, *, buttons=None, reply_to=None) -> str:
        self.sent.append(text)
        return str(900 + len(self.sent))

    async def answer_callback(self, callback_id, text="") -> None:
        pass

    async def edit(self, message_id, text, *, buttons=None) -> None:
        pass


async def lay(session, now, *, co2=600, temp=22.0, rh=45.0):
    """Samples every 10 s ending at ``now``. Each reading is a constant or a list
    of ``(minutes, value)`` segments, oldest first; one reading may be segmented,
    the others stay constant."""
    segmented = [v for v in (co2, temp, rh) if isinstance(v, list)]
    assert len(segmented) <= 1
    spec = segmented[0] if segmented else [(1, None)]
    # The newest sample sits exactly at ``now``.
    bounds = list(itertools.accumulate(minutes * 6 for minutes, _ in spec))
    total = bounds[-1]

    def pick(reading, i):
        if not isinstance(reading, list):
            return reading
        for bound, (_, value) in zip(bounds, spec):
            if i < bound:
                return value
        return spec[-1][1]

    boot = f"b{next(_boots)}"
    rows = []
    for i in range(total + 1):
        ts = now - timedelta(seconds=10 * (total - i))
        rows.append(sample(ts, i + 1, boot=boot, co2=pick(co2, min(i, total - 1)),
                           temp=pick(temp, min(i, total - 1)), rh=pick(rh, min(i, total - 1))))
    session.add_all(rows)
    await session.flush()
    return rows


async def _evaluate(session, notifier, now, **kw):
    return await alerts.evaluate(session, notifier, now=now, **kw)


async def _active(session):
    return {a.alert_key: a for a in await alerts_service.list_active(session, domain="environment")}


async def _journal(session):
    return list((await session.execute(select(Notification).order_by(Notification.id))).scalars())


# ── CO2: the stuffy-room message ──────────────────────────────────────────────
async def test_five_minutes_of_stuffy_air_sends_one_message_and_a_badge(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(20, 600), (5, 1500)])

    sent = await _evaluate(db_session, notifier, NOW)

    assert [r.category for r in sent] == ["environment"]
    assert notifier.sent == ["Душно: CO₂ 1500 ppm. Открой окно минут на 10."]
    active = await _active(db_session)
    assert active["env_co2_bad"].severity == "warn" and active["env_co2_bad"].domain == "environment"
    # It has only been high for 5 minutes, so the 15-minute warn rule is still quiet.
    assert "env_co2_warn" not in active


async def test_the_episode_is_identified_by_when_it_began(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(20, 1000), (6, 1500)])
    (row,) = await _evaluate(db_session, notifier, NOW)

    began = (NOW - timedelta(minutes=6)).strftime("%Y%m%dT%H%MZ")
    assert row.dedupe_key == f"env:env_co2_bad:{began}"
    assert (await _active(db_session))["env_co2_bad"].entity_ref == began


@pytest.mark.parametrize(
    "segments, why",
    [
        ([(20, 1000), (4, 1500)], "only four minutes"),
        ([(20, 1000), (4, 1500), (1, 1399)], "the newest snapshots dipped below the line"),
        ([(3, 1500), (1, 1100), (2, 1500)], "one low stretch inside the window"),
        ([(5, 1399)], "just under the threshold"),
    ],
)
async def test_it_does_not_fire_without_a_sustained_breach(db_session, segments, why):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=segments)
    assert await _evaluate(db_session, notifier, NOW) == [], why
    assert notifier.sent == [] and "env_co2_bad" not in await _active(db_session)


async def test_the_threshold_itself_counts(db_session):
    await lay(db_session, NOW, co2=[(6, 1400)])
    assert len(await _evaluate(db_session, FakeNotifier(), NOW)) == 1


async def test_a_reporting_gap_is_not_a_sustained_breach(db_session):
    # Two samples of 1500, four minutes of silence, then two more: every snapshot is
    # past the line but the window is nowhere near covered.
    for minutes in (-5, 0):
        await lay(db_session, NOW + timedelta(minutes=minutes), co2=[(0, 1500)] if False else 1500) if False else None
    rows = [sample(NOW - timedelta(seconds=s), 100 + i, boot="gap", co2=1500)
            for i, s in enumerate((300, 290, 20, 10, 0))]
    db_session.add_all(rows)
    await db_session.flush()
    assert await _evaluate(db_session, FakeNotifier(), NOW) == []


async def test_a_station_that_stopped_reporting_does_not_fire_on_old_readings(db_session):
    await lay(db_session, NOW - timedelta(minutes=3), co2=[(10, 1600)])  # the newest is 3 min old
    assert await _evaluate(db_session, FakeNotifier(), NOW) == []


async def test_a_second_pass_over_the_same_episode_says_nothing_more(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)
    for extra in range(1, 6):
        assert await _evaluate(db_session, notifier, NOW + timedelta(seconds=30 * extra)) == []
    assert len(notifier.sent) == 1
    assert len([a for a in (await _active(db_session)).values() if a.alert_key == "env_co2_bad"]) == 1


async def test_a_long_episode_never_speaks_twice_even_after_the_cooldown(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)
    later = NOW + timedelta(hours=3)  # cooldown long gone, the room is still stuffy
    await lay(db_session, later, co2=[(200, 1500)])
    await _evaluate(db_session, notifier, later)
    assert len(notifier.sent) == 1


# ── Hysteresis and "back to normal" ───────────────────────────────────────────
async def test_the_badge_stays_until_the_air_is_clearly_better_and_then_one_note_goes(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)

    # Hovering just under the line (1300 > 1400 * 0.9): still the same episode.
    t1 = NOW + timedelta(minutes=10)
    await lay(db_session, t1, co2=[(9, 1300)])
    assert await _evaluate(db_session, notifier, t1) == []
    assert "env_co2_bad" in await _active(db_session) and len(notifier.sent) == 1

    # Clearly back: below 1260 for three minutes.
    t2 = t1 + timedelta(minutes=4)
    await lay(db_session, t2, co2=[(4, 1100)])
    (ok,) = await _evaluate(db_session, notifier, t2)
    assert notifier.sent[-1] == "Воздух в норме: 1100 ppm"
    assert ok.dedupe_key.endswith(":ok")
    assert "env_co2_bad" not in await _active(db_session)

    # And only once.
    assert await _evaluate(db_session, notifier, t2 + timedelta(seconds=30)) == []
    assert len(notifier.sent) == 2


async def test_no_back_to_normal_for_an_episode_that_never_spoke(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NIGHT, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NIGHT)  # quiet hours: badge only
    assert notifier.sent == [] and "env_co2_bad" in await _active(db_session)

    t2 = NIGHT + timedelta(minutes=14)
    await lay(db_session, t2, co2=[(5, 800)])
    assert await _evaluate(db_session, notifier, t2) == []
    assert notifier.sent == [] and "env_co2_bad" not in await _active(db_session)


async def test_back_to_normal_is_dropped_not_delayed_by_quiet_hours(db_session):
    notifier = FakeNotifier()
    evening = at("2026-10-04T22:50:00")  # 01:50 local, just before quiet hours start
    await lay(db_session, evening, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, evening)
    assert len(notifier.sent) == 1

    back = evening + timedelta(minutes=14)  # 02:04 local: quiet
    await lay(db_session, back, co2=[(5, 800)])
    await _evaluate(db_session, notifier, back)
    assert "env_co2_bad" not in await _active(db_session)
    assert len(notifier.sent) == 1

    # Hours later, in the clear, the stale note does not turn up.
    morning = at("2026-10-05T08:00:00")
    await lay(db_session, morning, co2=[(30, 700)])
    await _evaluate(db_session, notifier, morning)
    assert len(notifier.sent) == 1


async def test_a_back_to_normal_sent_late_is_not_sent_at_all(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)

    # The air has been fine for half an hour before the next evaluation notices.
    later = NOW + timedelta(minutes=40)
    await lay(db_session, later, co2=[(30, 700)])
    await _evaluate(db_session, notifier, later)
    assert len(notifier.sent) == 1
    assert "env_co2_bad" not in await _active(db_session)


# ── The cooldown ──────────────────────────────────────────────────────────────
async def test_a_new_episode_inside_the_cooldown_raises_the_badge_but_stays_silent(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)
    back = NOW + timedelta(minutes=15)
    await lay(db_session, back, co2=[(5, 700)])
    await _evaluate(db_session, notifier, back)  # ends, "back to normal"
    assert len(notifier.sent) == 2

    again = NOW + timedelta(minutes=45)  # 45 min after the first message, 2 h cooldown
    await lay(db_session, again, co2=[(10, 1600)])
    await _evaluate(db_session, notifier, again)
    assert "env_co2_bad" in await _active(db_session)
    assert len(notifier.sent) == 2


async def test_after_the_cooldown_a_new_episode_speaks_again(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)

    clear = NOW + timedelta(hours=1)  # the air recovers in between (episode over)
    await lay(db_session, clear, co2=[(20, 700)])
    await _evaluate(db_session, notifier, clear)
    again = NOW + timedelta(hours=2, minutes=5)
    await lay(db_session, again, co2=[(10, 1600)])
    await _evaluate(db_session, notifier, again)
    assert [m for m in notifier.sent if m.startswith("Душно")] == [
        "Душно: CO₂ 1500 ppm. Открой окно минут на 10.",
        "Душно: CO₂ 1600 ppm. Открой окно минут на 10.",
    ]


# ── Quiet hours ───────────────────────────────────────────────────────────────
async def test_nothing_is_sent_at_night_but_the_badge_is_raised(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NIGHT, co2=[(10, 1500)])
    assert await _evaluate(db_session, notifier, NIGHT) == []
    assert notifier.sent == [] and "env_co2_bad" in await _active(db_session)


async def test_a_room_still_stuffy_when_quiet_hours_end_gets_its_message_then(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NIGHT, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NIGHT)

    morning = at("2026-10-05T07:01:00")  # 10:01 local
    await lay(db_session, morning, co2=[(10, 1700)])
    (row,) = await _evaluate(db_session, notifier, morning)
    assert notifier.sent == ["Душно: CO₂ 1700 ppm. Открой окно минут на 10."]
    assert row.dedupe_key.startswith("env:env_co2_bad:")


async def test_it_ignores_the_daily_budget_of_the_other_messages(db_session):
    for i in range(4):  # the day's budget of self-started messages is spent
        db_session.add(Notification(sent_at=delivery.now_local(), category="nudge", channel="telegram",
                                    dedupe_key=f"nudge:x{i}:2026-10-05T0{i}"))
    await db_session.flush()
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    assert len(await _evaluate(db_session, notifier, NOW)) == 1


# ── The switches ──────────────────────────────────────────────────────────────
async def test_alerts_switched_off_raise_nothing_and_clear_what_shows(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)
    assert "env_co2_bad" in await _active(db_session)

    await env_settings.set_settings(db_session, {"alerts_enabled": False})
    later = NOW + timedelta(minutes=5)
    await lay(db_session, later, co2=[(10, 1700)])
    assert await _evaluate(db_session, notifier, later) == []
    assert await _active(db_session) == {} and len(notifier.sent) == 1


async def test_with_telegram_off_only_the_badge_appears(db_session):
    await env_settings.set_settings(db_session, {"alert_telegram": False})
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    assert await _evaluate(db_session, notifier, NOW) == []
    assert notifier.sent == [] and "env_co2_bad" in await _active(db_session)


async def test_the_category_toggle_in_proactive_settings_silences_the_message(db_session):
    from vitals.services.proactive import prefs

    stored = await prefs.get_prefs(db_session)
    await prefs.set_prefs(db_session, {**stored, "nudges": {**stored["nudges"], "environment": False}})
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    assert await _evaluate(db_session, notifier, NOW) == []
    assert notifier.sent == [] and "env_co2_bad" in await _active(db_session)


async def test_without_a_channel_the_badges_still_work(db_session):
    await lay(db_session, NOW, co2=[(10, 1500)])
    assert await _evaluate(db_session, None, NOW) == []
    assert "env_co2_bad" in await _active(db_session)


async def test_the_bot_master_switch_silences_the_messages_but_not_the_badge(db_session):
    await modules_service.set_module_enabled(db_session, key="signals", enabled=False)
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    assert await _evaluate(db_session, notifier, NOW) == []
    assert notifier.sent == [] and "env_co2_bad" in await _active(db_session)


# ── The other rules ───────────────────────────────────────────────────────────
async def test_warn_level_co2_is_a_badge_without_a_message(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(16, 1100)])
    assert await _evaluate(db_session, notifier, NOW) == []
    badge = (await _active(db_session))["env_co2_warn"]
    assert badge.severity == "info" and notifier.sent == []
    assert "env_co2_bad" not in await _active(db_session)


@pytest.mark.parametrize(
    "temp, fires, text",
    [(27.0, True, "В комнате 27,0 °C, жарковато."), (27.2, True, "В комнате 27,2 °C, жарковато."),
     (26.9, False, None)],
)
async def test_a_hot_room_fires_one_degree_past_the_comfort_limit(db_session, temp, fires, text):
    notifier = FakeNotifier()
    await lay(db_session, NOW, temp=[(16, temp)])
    await _evaluate(db_session, notifier, NOW)
    assert ("env_temp_high" in await _active(db_session)) is fires
    assert notifier.sent == ([text] if fires else [])


@pytest.mark.parametrize("temp, fires", [(17.0, True), (16.4, True), (17.1, False)])
async def test_a_cool_room_fires_one_degree_below_the_comfort_limit(db_session, temp, fires):
    notifier = FakeNotifier()
    await lay(db_session, NOW, temp=[(16, temp)])
    await _evaluate(db_session, notifier, NOW)
    assert ("env_temp_low" in await _active(db_session)) is fires
    assert notifier.sent == ([f"В комнате {temp:.1f}".replace(".", ",") + " °C, прохладно."] if fires else [])


async def test_temperature_follows_the_owners_comfort_range(db_session):
    await env_settings.set_settings(db_session, {"temp_day_max": 23.0})
    notifier = FakeNotifier()
    await lay(db_session, NOW, temp=[(16, 24.5)])
    await _evaluate(db_session, notifier, NOW)
    assert notifier.sent == ["В комнате 24,5 °C, жарковато."]


async def test_the_sleeping_range_never_alerts(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, temp=[(30, 21.0)])  # past the sleeping 17-20, inside the day's 18-26
    await _evaluate(db_session, notifier, NOW)
    assert notifier.sent == [] and not [k for k in await _active(db_session) if k.startswith("env_temp")]


async def test_a_temperature_episode_ends_with_its_own_note(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, temp=[(16, 27.5)])
    await _evaluate(db_session, notifier, NOW)
    back = NOW + timedelta(minutes=5)
    await lay(db_session, back, temp=[(5, 25.0)])
    await _evaluate(db_session, notifier, back)
    assert notifier.sent[-1] == "Температура в норме: 25,0 °C"
    assert "env_temp_high" not in await _active(db_session)


@pytest.mark.parametrize("rh, fires", [(29.9, True), (30.0, False), (12.0, True)])
async def test_dry_air_needs_an_hour_below_the_alert_level(db_session, rh, fires):
    notifier = FakeNotifier()
    await lay(db_session, NOW, rh=[(61, rh)])
    await _evaluate(db_session, notifier, NOW)
    assert ("env_rh_low" in await _active(db_session)) is fires
    assert notifier.sent == ([f"Сухой воздух: {round(rh)}%."] if fires else [])


async def test_dry_air_for_less_than_an_hour_is_not_an_alert(db_session):
    await lay(db_session, NOW, rh=[(40, 20.0)])
    assert await _evaluate(db_session, FakeNotifier(), NOW) == []


@pytest.mark.parametrize("rh, fires", [(70.1, True), (70.0, False), (85.0, True)])
async def test_humid_air_needs_an_hour_above_the_alert_level(db_session, rh, fires):
    notifier = FakeNotifier()
    await lay(db_session, NOW, rh=[(61, rh)])
    await _evaluate(db_session, notifier, NOW)
    assert ("env_rh_high" in await _active(db_session)) is fires
    assert notifier.sent == ([f"Влажно: {round(rh)}%."] if fires else [])


async def test_humidity_hysteresis_is_ten_percent(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, rh=[(61, 75.0)])
    await _evaluate(db_session, notifier, NOW)
    # 64 is still above 70 * 0.9 = 63: the episode is not over.
    t1 = NOW + timedelta(minutes=5)
    await lay(db_session, t1, rh=[(5, 64.0)])
    await _evaluate(db_session, notifier, t1)
    assert "env_rh_high" in await _active(db_session)
    t2 = t1 + timedelta(minutes=5)
    await lay(db_session, t2, rh=[(5, 55.0)])
    await _evaluate(db_session, notifier, t2)
    assert "env_rh_high" not in await _active(db_session)
    assert notifier.sent[-1] == "Влажность в норме: 55%"


# ── The station falling silent ────────────────────────────────────────────────
async def _poll_state(redis, now, **fields):
    from vitals.services.environment.live import station_key

    await redis.hset(station_key("bedroom"), mapping={k: v.isoformat() for k, v in fields.items()})


async def test_a_silent_station_raises_a_badge_and_one_message_per_episode(db_session, redis):
    notifier = FakeNotifier()
    await lay(db_session, NOW - timedelta(minutes=20), co2=[(5, 700)])
    await _poll_state(redis, NOW, last_error_at=NOW - timedelta(minutes=1))

    (row,) = await _evaluate(db_session, notifier, NOW, redis=redis)
    assert notifier.sent == ["Станция молчит 20 мин: проверь питание и Wi-Fi."]
    badge = (await _active(db_session))["env_station_silent"]
    assert badge.severity == "warn" and badge.entity_ref in row.dedupe_key

    # Five minutes on, still silent: the same episode does not speak again.
    assert await _evaluate(db_session, notifier, NOW + timedelta(minutes=5), redis=redis) == []
    assert len(notifier.sent) == 1


async def test_a_station_that_is_back_clears_the_badge_without_a_message(db_session, redis):
    notifier = FakeNotifier()
    await lay(db_session, NOW - timedelta(minutes=20), co2=[(5, 700)])
    await _poll_state(redis, NOW, last_error_at=NOW - timedelta(minutes=1))
    await _evaluate(db_session, notifier, NOW, redis=redis)

    back = NOW + timedelta(minutes=2)
    await lay(db_session, back, co2=[(1, 700)])
    assert await _evaluate(db_session, notifier, back, redis=redis) == []
    assert "env_station_silent" not in await _active(db_session) and len(notifier.sent) == 1


async def test_fifteen_minutes_is_the_line(db_session, redis):
    await lay(db_session, NOW - timedelta(minutes=14), co2=[(5, 700)])
    await _poll_state(redis, NOW, last_error_at=NOW)
    assert await _evaluate(db_session, FakeNotifier(), NOW, redis=redis) == []
    assert "env_station_silent" not in await _active(db_session)


async def test_vitals_being_down_is_not_the_station_being_silent(db_session, redis):
    await lay(db_session, NOW - timedelta(minutes=30), co2=[(5, 700)])
    # The last time Vitals asked the station was before its own outage.
    await _poll_state(redis, NOW, last_ok_at=NOW - timedelta(minutes=29))
    assert await _evaluate(db_session, FakeNotifier(), NOW, redis=redis) == []
    assert "env_station_silent" not in await _active(db_session)


async def test_a_station_that_never_reported_is_not_silent(db_session, redis):
    await _poll_state(redis, NOW, last_error_at=NOW)
    assert await _evaluate(db_session, FakeNotifier(), NOW, redis=redis) == []


async def test_silence_at_night_waits_for_the_morning(db_session, redis):
    notifier = FakeNotifier()
    await lay(db_session, NIGHT - timedelta(minutes=30), co2=[(5, 700)])
    await _poll_state(redis, NIGHT, last_error_at=NIGHT)
    await _evaluate(db_session, notifier, NIGHT, redis=redis)
    assert notifier.sent == [] and "env_station_silent" in await _active(db_session)

    morning = at("2026-10-05T07:10:00")
    await _poll_state(redis, morning, last_error_at=morning)
    await _evaluate(db_session, notifier, morning, redis=redis)
    assert len(notifier.sent) == 1 and notifier.sent[0].startswith("Станция молчит ")


# ── Badge texts ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "lang, text",
    [("ru", "CO₂ в комнате выше 1400 ppm — пора проветрить."),
     ("en", "Room CO₂ is above 1400 ppm — time to air it out.")],
)
async def test_the_badge_speaks_the_owners_language(db_session, lang, text):
    token = current_lang.set(lang)
    try:
        await lay(db_session, NOW, co2=[(10, 1500)])
        await _evaluate(db_session, None, NOW)
    finally:
        current_lang.reset(token)
    assert (await _active(db_session))["env_co2_bad"].message == text


# ── Robustness ────────────────────────────────────────────────────────────────
async def test_a_dismissed_badge_comes_back_for_the_same_episode_without_a_new_message(db_session):
    notifier = FakeNotifier()
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, notifier, NOW)
    badge = (await _active(db_session))["env_co2_bad"]
    episode = badge.entity_ref
    await alerts_service.resolve_alert(db_session, badge.id)  # the owner dismisses it

    later = NOW + timedelta(minutes=1)
    await lay(db_session, later, co2=[(10, 1500)])
    assert await _evaluate(db_session, notifier, later) == []
    assert (await _active(db_session))["env_co2_bad"].entity_ref == episode
    assert len(notifier.sent) == 1


async def test_one_failing_rule_does_not_stop_the_others(db_session, monkeypatch):
    notifier = FakeNotifier()
    broken = alerts.RULES[0]
    monkeypatch.setattr(alerts, "RULES", (
        alerts.Rule(**{**broken.__dict__, "trigger": lambda c: 1 / 0}), *alerts.RULES[1:],
    ))
    await lay(db_session, NOW, co2=1500, temp=[(16, 28.0)])
    await _evaluate(db_session, notifier, NOW)
    assert "env_temp_high" in await _active(db_session)


async def test_alerts_are_in_the_environment_domain(db_session):
    await lay(db_session, NOW, co2=[(10, 1500)])
    await _evaluate(db_session, FakeNotifier(), NOW)
    rows = (await db_session.execute(select(SystemAlert))).scalars().all()
    assert rows and {r.domain for r in rows} == {"environment"}
    assert (await _journal(db_session))[0].category == "environment"


# ── The job ───────────────────────────────────────────────────────────────────
async def test_the_job_does_nothing_without_a_station(db_session, session_factory, redis, monkeypatch):
    monkeypatch.delenv("VITALS_ENV_STATION_URL", raising=False)
    await lay(db_session, NOW, co2=[(10, 1500)])
    await db_session.commit()
    await alerts.environment_alerts_job(session_factory, redis)
    assert await _active(db_session) == {}


async def test_the_job_with_the_module_off_clears_stale_badges(db_session, session_factory, redis, monkeypatch):
    monkeypatch.setenv("VITALS_ENV_STATION_URL", "http://station.test")
    await alerts_service.raise_alert(
        db_session, domain="environment", severity="warn", message="x", alert_key="env_co2_bad", entity_ref="e"
    )
    await db_session.commit()
    state = await modules_service.set_module_enabled(db_session, key="environment", enabled=False)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)

    await alerts.environment_alerts_job(session_factory, redis)
    assert await _active(db_session) == {}


async def test_the_job_evaluates_with_the_module_on(db_session, session_factory, redis, monkeypatch):
    from freezegun import freeze_time

    monkeypatch.setenv("VITALS_ENV_STATION_URL", "http://station.test")
    notifier = FakeNotifier()
    monkeypatch.setattr(alerts.channels, "build_notifier", lambda *a, **k: notifier)
    state = await modules_service.set_module_enabled(db_session, key="environment", enabled=True)
    await db_session.commit()
    await modules_service.prime_cache(redis, state)
    await lay(db_session, NOW, co2=[(10, 1500)])
    await db_session.commit()

    with freeze_time("2026-10-05T12:00:00"):
        await alerts.environment_alerts_job(session_factory, redis)
    assert notifier.sent == ["Душно: CO₂ 1500 ppm. Открой окно минут на 10."]
    assert "env_co2_bad" in await _active(db_session)
