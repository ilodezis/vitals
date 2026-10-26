"""The routine day — the owner's day, which ends at ``day_end`` (05:00 by
default), not at midnight. A skincare round at 01:00 belongs to the evening
before: its plan, its ticks and the conflict check all land there.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest
from freezegun import freeze_time

from vitals.services import skincare_service
from vitals.services.proactive import prefs
from vitals.utils.timeutils import day_of

# 22:00 UTC on 21.10 is 01:00 on 22.10 in Chisinau (EEST, +3).
ONE_AM_THURSDAY_UTC = "2026-10-21 22:00:00"


# ── The pure rule ────────────────────────────────────────────────────────────
def test_before_the_day_end_it_is_still_yesterday():
    five = time(5, 0)
    assert day_of(datetime(2026, 10, 22, 1, 0), five) == date(2026, 10, 21)
    assert day_of(datetime(2026, 10, 22, 4, 59), five) == date(2026, 10, 21)
    assert day_of(datetime(2026, 10, 22, 5, 0), five) == date(2026, 10, 22)
    assert day_of(datetime(2026, 10, 21, 23, 30), five) == date(2026, 10, 21)


def test_a_day_ending_at_midnight_is_the_calendar():
    assert day_of(datetime(2026, 10, 22, 0, 30), time(0, 0)) == date(2026, 10, 22)


# ── The setting ──────────────────────────────────────────────────────────────
def test_day_end_defaults_and_stays_within_the_night():
    assert prefs.sanitize({})["day_end"] == "05:00"
    assert prefs.sanitize({"day_end": "garbage"})["day_end"] == "05:00"
    assert prefs.sanitize({"day_end": "03:30"})["day_end"] == "03:30"
    # Past 06:00 a morning round would land on the day before.
    assert prefs.sanitize({"day_end": "09:00"})["day_end"] == prefs.DAY_END_MAX


async def test_routine_today_reads_the_stored_day_end(db_session):
    one_am = datetime(2026, 10, 22, 1, 0)
    assert await prefs.routine_today(db_session, one_am) == date(2026, 10, 21)

    await prefs.set_prefs(db_session, {"day_end": "00:00"})
    assert await prefs.routine_today(db_session, one_am) == date(2026, 10, 22)


async def test_the_settings_api_saves_and_clamps_the_day_end(auth_client, db_session):
    r = await auth_client.post("/api/v1/settings/proactive", json={"day_end": "07:30"})
    assert r.status_code == 200
    assert r.json()["adjusted"] is True
    assert (await prefs.get_prefs(db_session))["day_end"] == prefs.DAY_END_MAX

    await auth_client.post("/api/v1/settings/proactive", json={"day_end": "04:00"})
    view = (await auth_client.get("/api/v1/settings")).json()
    assert view["proactive"]["day_end"] == "04:00"


# ── Where it applies ─────────────────────────────────────────────────────────
async def test_at_one_am_the_skincare_screen_is_on_the_evening_before(db_session):
    await skincare_service.add_product(
        db_session, name="Дифферин", type="Ретиноид", default_time="evening", schedule_days=[3]
    )
    await db_session.commit()

    with freeze_time(ONE_AM_THURSDAY_UTC):
        view = await skincare_service.collect(db_session)

    assert view["today"] == "2026-10-21"
    assert [i["name"] for i in view["plan"]["evening"]] == ["Дифферин"]


async def test_at_one_am_the_conflict_check_reads_the_evening_before(db_session):
    """«Today's checklist» for a rule fired from another domain is the routine
    day's — a peel ticked at 01:00 is still that evening's peel."""
    await skincare_service.upsert_log(db_session, on_date=date(2026, 10, 21), peel=True)
    await db_session.commit()

    with freeze_time(ONE_AM_THURSDAY_UTC):
        items = await skincare_service.resolve_today(db_session)

    assert items and items[0]["peel"] is True


# ── Notes ────────────────────────────────────────────────────────────────────
async def test_one_note_per_slot_and_day_replaced_and_removed(db_session):
    day = date(2026, 10, 21)
    await skincare_service.set_note(db_session, on_date=day, slot="evening", text="  только на лоб ")
    await skincare_service.set_note(db_session, on_date=day, slot="evening", text="пропусти ретиноид")
    plan = await skincare_service.plan_for(db_session, day)
    assert plan["notes"] == {"evening": "пропусти ретиноид"}

    assert await skincare_service.set_note(db_session, on_date=day, slot="evening", text="") is None
    assert (await skincare_service.plan_for(db_session, day))["notes"] == {}


async def test_a_note_refuses_an_unknown_slot_and_a_wall_of_text(db_session):
    day = date(2026, 10, 21)
    with pytest.raises(ValueError):
        await skincare_service.set_note(db_session, on_date=day, slot="noon", text="x")
    with pytest.raises(ValueError):
        await skincare_service.set_note(
            db_session, on_date=day, slot="evening", text="x" * (skincare_service.NOTE_MAX_CHARS + 1)
        )
