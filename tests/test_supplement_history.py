"""When a supplement was started and stopped.

The catalog's ``active`` flag only says what is taken *now*; switching it off used
to erase when it had been switched on, so "did the skin change after starting X"
had no date to look from. Every path that flips the flag — web form, toggle,
connector — now writes the period history, and every reader that talks about
supplements over time reads it.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from vitals.enums import Source
from vitals.models.supplements import Supplement, SupplementPeriod
from vitals.services import supplements_service, timeline_service

DAY = date(2026, 6, 1)


@pytest.fixture
def on_day(monkeypatch):
    """Pin the service's idea of today; returns a setter to move it."""
    current = {"day": DAY}
    monkeypatch.setattr(supplements_service, "today_local", lambda: current["day"])

    def move(day: date) -> None:
        current["day"] = day

    return move


async def _periods(db_session, supplement_id: int) -> list[SupplementPeriod]:
    result = await db_session.execute(
        select(SupplementPeriod)
        .where(SupplementPeriod.supplement_id == supplement_id)
        .order_by(SupplementPeriod.date, SupplementPeriod.id)
    )
    return list(result.scalars().all())


# ── The service keeps the history ─────────────────────────────────────────────
async def test_adding_an_active_supplement_opens_a_period(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")

    (period,) = await _periods(db_session, row.id)
    assert (period.date, period.end_date, period.source) == (DAY, None, Source.MANUAL.value)
    assert period.domain == "supplements"


async def test_adding_a_paused_supplement_records_nothing(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc", active=False)
    assert await _periods(db_session, row.id) == []


async def test_stop_and_restart_on_later_days_are_two_periods(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=10))
    await supplements_service.set_active(db_session, row.id, False)
    on_day(DAY + timedelta(days=20))
    await supplements_service.set_active(db_session, row.id, True)

    first, second = await _periods(db_session, row.id)
    assert (first.date, first.end_date) == (DAY, DAY + timedelta(days=10))
    assert (second.date, second.end_date) == (DAY + timedelta(days=20), None)


async def test_a_same_day_off_and_on_is_not_a_break(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=5))
    await supplements_service.set_active(db_session, row.id, False)
    await supplements_service.set_active(db_session, row.id, True)

    (period,) = await _periods(db_session, row.id)
    assert (period.date, period.end_date) == (DAY, None)


async def test_repeating_the_same_state_changes_nothing(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=3))
    await supplements_service.set_active(db_session, row.id, True)
    await supplements_service.update_supplement(db_session, row.id, name="Zinc 25 mg")

    (period,) = await _periods(db_session, row.id)
    assert (period.date, period.end_date) == (DAY, None)


async def test_an_edit_that_switches_it_off_closes_the_period(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=7))
    await supplements_service.update_supplement(db_session, row.id, name="Zinc", active=False)

    (period,) = await _periods(db_session, row.id)
    assert period.end_date == DAY + timedelta(days=7)


# ── The web API shows it ──────────────────────────────────────────────────────
async def test_the_dashboard_says_since_when_and_when_it_stopped(auth_client, db_session, on_day):
    taken = await supplements_service.add_supplement(db_session, name="Zinc")
    paused = await supplements_service.add_supplement(db_session, name="Iron")
    await db_session.commit()
    on_day(DAY + timedelta(days=4))

    toggled = await auth_client.post(
        f"/api/v1/supplements/{paused.id}/toggle", json={"active": False}
    )
    assert toggled.status_code == 200
    assert toggled.json()["stoppedOn"] == (DAY + timedelta(days=4)).isoformat()
    assert toggled.json()["since"] is None

    body = (await auth_client.get("/api/v1/supplements")).json()
    (active,) = body["active"]
    assert active["id"] == taken.id and active["since"] == DAY.isoformat()
    (archived,) = body["archived"]
    assert archived["stoppedOn"] == (DAY + timedelta(days=4)).isoformat()


# ── The connector writes and reads it ─────────────────────────────────────────
@pytest.fixture
def mcp_router(session_factory, monkeypatch):
    router = pytest.importorskip("web.routers.mcp")
    monkeypatch.setattr(router, "get_session_factory", lambda: session_factory)
    return router


@pytest.fixture
async def supplements_on(session_factory):
    from vitals.services import modules_service

    async with session_factory() as session:
        await modules_service.set_module_enabled(session, key="supplements", enabled=True)
        await session.commit()


async def test_connector_switches_are_stamped_and_read_back(
    mcp_router, supplements_on, session_factory, on_day
):
    added = await mcp_router.add_supplement(name="Magnesium")
    assert added["source"] == Source.MCP.value
    on_day(DAY + timedelta(days=12))
    await mcp_router.set_supplement_active(supplement_id=added["id"], active=False)

    async with session_factory() as session:
        (period,) = await _periods(session, added["id"])
    assert period.source == Source.MCP.value

    (row,) = await mcp_router.get_supplements_catalog()
    assert row["periods"] == [
        {"start": DAY.isoformat(), "end": (DAY + timedelta(days=12)).isoformat()}
    ]


async def test_connector_marks_a_backfilled_start_as_inferred(
    mcp_router, supplements_on, session_factory
):
    async with session_factory() as session:
        row = Supplement(name="Omega-3", key="omega_3", domain="supplements", active=True)
        session.add(row)
        await session.flush()
        session.add(SupplementPeriod(
            supplement_id=row.id, date=DAY, domain="supplements", source=Source.INFERRED.value,
        ))
        await session.commit()

    (out,) = await mcp_router.get_supplements_catalog()
    assert out["periods"] == [{"start": DAY.isoformat(), "inferred": True}]


# ── Timeline, chart flags, report context ─────────────────────────────────────
async def test_timeline_and_chart_flags_come_from_the_periods(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=9))
    await supplements_service.set_active(db_session, row.id, False)
    inferred = Supplement(name="Omega-3", key="omega_3", domain="supplements", active=True)
    db_session.add(inferred)
    await db_session.flush()
    db_session.add(SupplementPeriod(
        supplement_id=inferred.id, date=DAY - timedelta(days=30), domain="supplements",
        source=Source.INFERRED.value,
    ))
    await db_session.commit()

    events = await timeline_service.list_events(db_session)
    supp = {e.ref.split(":")[0]: e for e in events if e.domain == "supplements" and "Zinc" in e.title}
    assert supp["supplement_started"].date == DAY
    assert supp["supplement_stopped"].date == DAY + timedelta(days=9)
    omega = next(e for e in events if "Omega-3" in e.title)
    assert omega.detail  # the date is flagged as approximate

    plain = await timeline_service.overlays_for(db_session, domain="weight")
    assert plain == []
    flags = await timeline_service.overlays_for(db_session, domain="weight", with_supplements=True)
    assert sorted(f["start"] for f in flags) == [DAY.isoformat(), (DAY + timedelta(days=9)).isoformat()]
    # A backfilled start is a guess — not drawn as a line on a chart.
    assert not any("Omega-3" in f["label"] for f in flags)


@pytest.mark.usefixtures("all_modules_on")
async def test_report_context_carries_the_history_and_the_ones_stopped_in_window(
    db_session, on_day
):
    from vitals.services import digest_service

    kept = await supplements_service.add_supplement(db_session, name="Zinc")
    dropped = await supplements_service.add_supplement(db_session, name="Iron")
    long_gone = await supplements_service.add_supplement(db_session, name="Biotin")
    on_day(DAY + timedelta(days=1))
    await supplements_service.set_active(db_session, long_gone.id, False)
    report_day = DAY + timedelta(days=60)
    on_day(report_day - timedelta(days=2))
    await supplements_service.set_active(db_session, dropped.id, False)
    await db_session.commit()

    ctx = await digest_service.assemble_context(db_session, on_date=report_day)

    by_name = {s["name"]: s for s in ctx["supplements"]}
    assert set(by_name) == {"Zinc", "Iron"}  # Biotin stopped long before the window
    assert by_name["Zinc"]["periods"] == [{"start": DAY.isoformat()}]
    assert by_name["Iron"]["active"] is False
    assert by_name["Iron"]["periods"][-1]["end"] == (report_day - timedelta(days=2)).isoformat()
    assert kept.id != dropped.id


# ── Backups ───────────────────────────────────────────────────────────────────
async def test_full_backup_round_trips_the_periods(db_session, on_day):
    from vitals.services.data_portability_service import export_full, export_llm, import_full

    row = await supplements_service.add_supplement(db_session, name="Zinc")
    on_day(DAY + timedelta(days=3))
    await supplements_service.set_active(db_session, row.id, False)
    await db_session.commit()

    snapshot = await export_full(db_session)
    assert len(snapshot["supplement_periods"]) == 1

    stats = await import_full(db_session, snapshot)
    await db_session.commit()
    assert stats.counts["supplement_periods"] == 1
    (period,) = await _periods(db_session, row.id)
    assert (period.date, period.end_date) == (DAY, DAY + timedelta(days=3))

    llm = await export_llm(db_session)
    assert llm["supplements"][0]["periods"] == [
        {"start": DAY.isoformat(), "end": (DAY + timedelta(days=3)).isoformat()}
    ]


async def test_deleting_a_supplement_takes_its_history_with_it(db_session, on_day):
    row = await supplements_service.add_supplement(db_session, name="Zinc")
    await db_session.commit()
    assert await supplements_service.delete_supplement(db_session, row.id)
    await db_session.commit()
    assert (await db_session.execute(select(SupplementPeriod))).scalars().all() == []

