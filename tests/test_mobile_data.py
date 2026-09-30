"""The screen shows data, or says why not: which Garmin day counts as "latest",
and that the recovery overview names the day when it is not today."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from vitals.models.garmin import GarminDaily
from vitals.services import garmin_service


@pytest.mark.asyncio
async def test_a_placeholder_row_is_not_the_latest_day(db_session):
    """The sync writes a row when the date turns, hours before the watch reports
    anything. Returned as "the latest day" that empty row drew a whole screen of
    dashes with yesterday's complete row sitting right behind it."""
    db_session.add_all([
        GarminDaily(date=date(2026, 8, 1), domain="garmin", sleep_score=82, steps=9000),
        # today: the row exists, the watch has reported nothing onto it yet
        GarminDaily(date=date(2026, 8, 2), domain="garmin"),
    ])
    await db_session.flush()

    latest = await garmin_service.latest_daily(db_session)
    assert latest is not None
    assert latest.date == date(2026, 8, 1)
    assert latest.sleep_score == 82


@pytest.mark.asyncio
async def test_the_recovery_overview_names_the_day_when_it_is_not_today(db_session, auth_client):
    """Showing yesterday's numbers silently is worse than showing none."""
    from vitals.utils.timeutils import today_local

    day = today_local().replace(day=1) - timedelta(days=1)
    db_session.add(GarminDaily(date=day, domain="garmin", sleep_score=71, steps=4200))
    await db_session.flush()

    r = await auth_client.get("/api/v1/recovery")
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == day.isoformat()
    assert data["today_date"] == today_local().isoformat()
    assert data["is_today"] is False
    assert data["headline"]["sleep_score"] == 71
