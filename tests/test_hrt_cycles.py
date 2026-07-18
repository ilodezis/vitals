"""HRT cycle tests — the schedule engine (pure), the active-release model,
cycle CRUD / auto-close, planned administrations, and the cycle UI flow."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from vitals.services import hrt_catalog, hrt_cycle_service, hrt_service
from vitals.utils.timeutils import today_local

pytestmark = pytest.mark.asyncio

ANCHOR = date(2026, 6, 1)


# ── Schedule engine (pure, no DB) ─────────────────────────────────────────────
async def test_expand_flat_fractional_interval():
    seg = [{"dose": 125, "interval_days": 3.5, "duration_days": 14}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=30))
    offsets = [(d - ANCHOR).days for d, _ in adm]
    assert offsets == [0, 4, 7, 10]
    assert {v for _, v in adm} == {125.0}


async def test_expand_linear_ramp():
    seg = [{"dose_start": 250, "dose_end": 500, "step": 50, "step_every_days": 7,
            "interval_days": 7, "duration_days": 28}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=45))
    assert [((d - ANCHOR).days, v) for d, v in adm] == [
        (0, 250.0), (7, 300.0), (14, 350.0), (21, 400.0)
    ]


async def test_expand_ramp_clamps_to_end():
    seg = [{"dose_start": 200, "dose_end": 300, "step": 100, "step_every_days": 7,
            "interval_days": 7, "duration_days": 28}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=45))
    doses = [v for _, v in adm]
    assert max(doses) == 300.0  # clamped, never overshoots dose_end


async def test_expand_two_segments_blast_then_open_cruise():
    segs = [{"dose": 500, "interval_days": 7, "duration_days": 14},
            {"dose": 150, "interval_days": 7}]
    adm = hrt_cycle_service.expand_schedule(segs, ANCHOR, ANCHOR, ANCHOR + timedelta(days=34))
    assert [((d - ANCHOR).days, v) for d, v in adm] == [
        (0, 500.0), (7, 500.0), (14, 150.0), (21, 150.0), (28, 150.0)
    ]


async def test_expand_windows_to_start_end():
    seg = [{"dose": 100, "interval_days": 7}]
    # Only administrations within [ANCHOR+10, ANCHOR+20] returned.
    adm = hrt_cycle_service.expand_schedule(
        seg, ANCHOR, ANCHOR + timedelta(days=10), ANCHOR + timedelta(days=20)
    )
    offsets = [(d - ANCHOR).days for d, _ in adm]
    assert offsets == [14]


async def test_expand_empty_schedule():
    assert hrt_cycle_service.expand_schedule([], ANCHOR, ANCHOR, ANCHOR + timedelta(days=10)) == []


# ── Active-release model ──────────────────────────────────────────────────────
async def test_release_series_single_dose_decay(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    d0 = date(2026, 6, 1)
    await hrt_service.log_dose(
        db_session, compound_key="testosterone_enanthate", on_date=d0, dose=250, unit="mg",
    )
    await db_session.commit()
    series = await hrt_cycle_service.release_series(
        db_session, start=d0, end=d0 + timedelta(days=9), include_planned=False,
    )
    # 250 mg × 0.72 fraction = 180 mg active at t0; halves every 4.5 days.
    assert series[0]["total_mg"] == pytest.approx(180.0, abs=0.5)
    assert series[9]["total_mg"] == pytest.approx(45.0, abs=0.5)  # 9 d = two half-lives
    assert series[0]["by_class"]["testosterone"] == pytest.approx(180.0, abs=0.5)


async def test_release_skips_non_mg_units(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    d0 = date(2026, 6, 1)
    # GH is dosed in IU — it must not contribute to the mg release curve.
    await hrt_service.log_dose(
        db_session, compound_key="somatropin", on_date=d0, dose=4,
    )
    await db_session.commit()
    series = await hrt_cycle_service.release_series(
        db_session, start=d0, end=d0 + timedelta(days=3), include_planned=False,
    )
    assert all(pt["total_mg"] == 0.0 for pt in series)


# ── Cycle CRUD ────────────────────────────────────────────────────────────────
async def test_add_open_cycle_closes_previous(db_session):
    c1 = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=date(2026, 5, 1),
    )
    await db_session.commit()
    c2 = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=date(2026, 6, 1),
    )
    await db_session.commit()
    await db_session.refresh(c1)
    assert c1.end_date == date(2026, 5, 31)  # auto-closed the day before c2
    assert c2.end_date is None


async def test_active_cycle_covers_today(db_session):
    await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local() - timedelta(days=5),
    )
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active is not None and active.kind == "course"


async def test_add_item_and_planned_administrations(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    item = await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 125, "interval_days": 3.5}],
    )
    await db_session.commit()
    assert item.compound_id is not None and item.unit == "mg"
    planned = await hrt_cycle_service.planned_administrations(
        db_session, start=today_local(), end=today_local() + timedelta(days=7),
    )
    assert len(planned) >= 2
    assert planned[0]["compound_key"] == "testosterone_enanthate"


async def test_add_item_requires_schedule(db_session):
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    with pytest.raises(ValueError):
        await hrt_cycle_service.add_cycle_item(
            db_session, cycle.id, compound_key="oxandrolone", schedule=[],
        )


async def test_resolve_active_includes_cycle_compound(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="trenbolone_acetate",
        schedule=[{"dose": 50, "interval_days": 2}],
    )
    await db_session.commit()
    items = await hrt_service.resolve_active(db_session)
    keys = {i["compound_key"]: i for i in items}
    assert "trenbolone_acetate" in keys
    assert keys["trenbolone_acetate"]["compound_class"] == "trenbolone"


# ── Cycle UI flow ─────────────────────────────────────────────────────────────
async def test_cycle_create_and_render(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    r = await auth_client.post(
        "/hrt/cycle",
        data={"kind": "course", "name": "Summer", "start_date": today_local().isoformat()},
    )
    assert r.status_code == 303
    add = await auth_client.post(
        f"/hrt/cycle/{(await hrt_cycle_service.active_cycle(db_session)).id}/item",
        data={"compound_key": "testosterone_enanthate", "dose": "250",
              "interval_days": "3.5", "duration_days": "70"},
    )
    assert add.status_code == 303
    page = await auth_client.get("/hrt")
    assert page.status_code == 200
    assert "Summer" in page.text
    assert "testosterone_enanthate" in page.text


async def test_release_json_endpoint(auth_client):
    r = await auth_client.get("/hrt/release.json?days_back=5&days_forward=5")
    assert r.status_code == 200
    body = r.json()
    assert "series" in body and len(body["series"]) == 11  # 5 back + today + 5 fwd


async def test_hrt_dashboard_renders_masthead_header(auth_client, db_session):
    """The masthead editorial header (masthead_header macro) renders on the HRT
    page — the section is registered in partials/masthead.html."""
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    r = await auth_client.get("/hrt")
    assert r.status_code == 200
    assert "mh-title" in r.text   # masthead editorial header rendered
    assert "mh-metric" in r.text  # the section's key-figures row rendered


# ── Cycle lifecycle chains (create-over, delete, switch, close) ───────────────
async def test_new_open_cycle_supersedes_same_day(db_session):
    """Creating a new open cycle the SAME day as the current one must switch the
    active cycle to the new one (the reported UI bug)."""
    a = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    b = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active is not None and active.id == b.id
    assert active.kind == "course"
    # The superseded same-day cycle must be closed (not left as a second open one).
    await db_session.refresh(a)
    assert a.end_date is not None


async def test_new_open_cycle_closes_earlier_open(db_session):
    a = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local() - timedelta(days=10)
    )
    await db_session.commit()
    b = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    await db_session.refresh(a)
    assert a.end_date == today_local() - timedelta(days=1)
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active.id == b.id


async def test_only_one_open_cycle_after_supersede(db_session):
    from sqlalchemy import select
    from vitals.models.hrt import HrtCycle
    for _ in range(3):
        await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
        await db_session.commit()
    open_cycles = (
        await db_session.execute(select(HrtCycle).where(HrtCycle.end_date.is_(None)))
    ).scalars().all()
    assert len(open_cycles) == 1


async def test_switch_kind_via_new_cycle(db_session):
    await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    await hrt_cycle_service.add_cycle(db_session, kind="pct", start_date=today_local())
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active.kind == "pct"


async def test_delete_active_cycle_makes_none_active(db_session):
    a = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    assert await hrt_cycle_service.delete_cycle(db_session, a.id) is True
    await db_session.commit()
    assert await hrt_cycle_service.active_cycle(db_session) is None


async def test_delete_cycle_cascades_items(db_session):
    from sqlalchemy import func, select
    from vitals.models.hrt import HrtCycleItem
    await hrt_catalog.sync_catalog(db_session)
    a = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, a.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 250, "interval_days": 3.5}],
    )
    await db_session.commit()
    await hrt_cycle_service.delete_cycle(db_session, a.id)
    await db_session.commit()
    n = (await db_session.execute(select(func.count()).select_from(HrtCycleItem))).scalar()
    assert n == 0


async def test_delete_reveals_previous_open_cycle_as_none(db_session):
    """After superseding then deleting the new cycle, the superseded one stays
    closed — no active cycle resurfaces (closed cycles are not 'open')."""
    await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local() - timedelta(days=5))
    await db_session.commit()
    b = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    await hrt_cycle_service.delete_cycle(db_session, b.id)
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    # The cruise cycle was closed yesterday when blast started → nothing active now.
    assert active is None


async def test_close_then_create_new(db_session):
    a = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local() - timedelta(days=3))
    await db_session.commit()
    await hrt_cycle_service.close_cycle(db_session, a.id, end_date=today_local())
    await db_session.commit()
    b = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active.id == b.id


async def test_add_remove_readd_item(db_session):
    await hrt_catalog.sync_catalog(db_session)
    a = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=today_local())
    await db_session.commit()
    it = await hrt_cycle_service.add_cycle_item(
        db_session, a.id, compound_key="oxandrolone", schedule=[{"dose": 20, "interval_days": 1}],
    )
    await db_session.commit()
    assert await hrt_cycle_service.delete_cycle_item(db_session, it.id) is True
    await db_session.commit()
    it2 = await hrt_cycle_service.add_cycle_item(
        db_session, a.id, compound_key="oxandrolone", schedule=[{"dose": 30, "interval_days": 1}],
    )
    await db_session.commit()
    await db_session.refresh(a)
    assert len(a.items) == 1 and a.items[0].id == it2.id


# ── Route-level: create-over-active reproduces the UI bug ─────────────────────
async def test_route_create_cycle_over_active_switches(auth_client, db_session):
    today = today_local().isoformat()
    r1 = await auth_client.post("/hrt/cycle", data={"kind": "course", "name": "First", "start_date": today})
    assert r1.status_code == 303
    r2 = await auth_client.post("/hrt/cycle", data={"kind": "course", "name": "Second", "start_date": today})
    assert r2.status_code == 303
    page = await auth_client.get("/hrt")
    assert "Second" in page.text
    # The old cycle's badge/name should no longer be the active one shown up top.
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active.name == "Second"


async def test_cycle_with_past_end_not_active(db_session):
    await hrt_cycle_service.add_cycle(
        db_session, kind="pct", start_date=today_local() - timedelta(days=30),
        end_date=today_local() - timedelta(days=1),
    )
    await db_session.commit()
    assert await hrt_cycle_service.active_cycle(db_session) is None


async def test_future_cycle_not_active_today(db_session):
    await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local() + timedelta(days=7),
    )
    await db_session.commit()
    assert await hrt_cycle_service.active_cycle(db_session) is None


# ── Per-item start offset (week-staggered courses) ────────────────────────────
async def test_item_offset_delays_planned_administrations(db_session):
    await hrt_catalog.sync_catalog(db_session)
    start = today_local()
    cycle = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=start)
    await db_session.commit()
    # Winstrol from week 5 (day 28), daily.
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="stanozolol_oral",
        schedule=[{"dose": 30, "interval_days": 1, "duration_days": 28}],
        start_offset_days=28,
    )
    await db_session.commit()
    planned = await hrt_cycle_service.planned_administrations(
        db_session, start=start, end=start + timedelta(days=60),
    )
    offsets = [(p["date"] - start).days for p in planned]
    assert offsets and min(offsets) == 28  # nothing before week 5
    assert max(offsets) == 28 + 27  # 28-day run from its own anchor


async def test_item_offset_zero_default_keeps_cycle_anchor(db_session):
    await hrt_catalog.sync_catalog(db_session)
    start = today_local()
    cycle = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=start)
    await db_session.commit()
    item = await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 125, "interval_days": 3.5}],
    )
    await db_session.commit()
    assert item.start_offset_days == 0
    planned = await hrt_cycle_service.planned_administrations(
        db_session, start=start, end=start + timedelta(days=7),
    )
    assert (planned[0]["date"] - start).days == 0


async def test_item_offset_grid_anchored_at_offset_not_cycle_start(db_session):
    await hrt_catalog.sync_catalog(db_session)
    start = today_local()
    cycle = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=start)
    await db_session.commit()
    # EOD anastrozole from week 3 — grid must run 14, 16, 18... off the offset.
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="anastrozole",
        schedule=[{"dose": 0.5, "interval_days": 2, "duration_days": 7}],
        start_offset_days=14,
    )
    await db_session.commit()
    planned = await hrt_cycle_service.planned_administrations(
        db_session, start=start, end=start + timedelta(days=30),
    )
    assert [(p["date"] - start).days for p in planned] == [14, 16, 18, 20]


async def test_item_offset_negative_rejected(db_session):
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    with pytest.raises(ValueError):
        await hrt_cycle_service.add_cycle_item(
            db_session, cycle.id, compound_key="oxandrolone",
            schedule=[{"dose": 20, "interval_days": 1}], start_offset_days=-7,
        )


async def test_item_offset_release_series_shifts(db_session):
    await hrt_catalog.sync_catalog(db_session)
    # The cycle must be active today for its plan to feed the release curve;
    # planned contributions are only projected from tomorrow onward.
    start = today_local()
    cycle = await hrt_cycle_service.add_cycle(db_session, kind="course", start_date=start)
    await db_session.commit()
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_propionate",
        schedule=[{"dose": 100, "interval_days": 2, "duration_days": 14}],
        start_offset_days=7,
    )
    await db_session.commit()
    series = await hrt_cycle_service.release_series(
        db_session, start=start, end=start + timedelta(days=10), include_planned=True,
    )
    # Zero active hormone until the item's own (offset) start.
    by_day = {p["date"]: p["total_mg"] for p in series}
    assert by_day[start.isoformat()] == 0.0
    assert by_day[(start + timedelta(days=6)).isoformat()] == 0.0
    assert by_day[(start + timedelta(days=7)).isoformat()] > 0.0


async def test_route_add_item_with_start_week(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local().isoformat()
    r = await auth_client.post("/hrt/cycle", data={"kind": "course", "start_date": today})
    assert r.status_code == 303
    cycle = await hrt_cycle_service.active_cycle(db_session)
    r = await auth_client.post(
        f"/hrt/cycle/{cycle.id}/item",
        data={"compound_key": "stanozolol_oral", "dose": "30", "interval_days": "1",
              "duration_days": "28", "start_week": "5"},
    )
    assert r.status_code == 303
    await db_session.refresh(cycle)
    assert cycle.items[0].start_offset_days == 28  # (5-1)*7


async def test_route_add_item_blank_start_week_defaults_zero(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    today = today_local().isoformat()
    await auth_client.post("/hrt/cycle", data={"kind": "course", "start_date": today})
    cycle = await hrt_cycle_service.active_cycle(db_session)
    r = await auth_client.post(
        f"/hrt/cycle/{cycle.id}/item",
        data={"compound_key": "testosterone_enanthate", "dose": "125",
              "interval_days": "3.5", "start_week": ""},
    )
    assert r.status_code == 303
    await db_session.refresh(cycle)
    assert cycle.items[0].start_offset_days == 0


async def test_add_cycle_rejects_unknown_kind(db_session):
    with pytest.raises(ValueError, match="kind"):
        await hrt_cycle_service.add_cycle(
            db_session, kind="blast", start_date=today_local(),
        )


# ── Fix pack: date/offset validation ──────────────────────────────────────────
async def test_route_cycle_garbage_date_is_422(auth_client):
    r = await auth_client.post(
        "/hrt/cycle", data={"kind": "course", "start_date": "not-a-date"},
    )
    assert r.status_code == 422
    assert "invalid date" in r.json()["error"]


async def test_close_cycle_rejects_end_before_start(db_session):
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    with pytest.raises(ValueError, match="before the cycle"):
        await hrt_cycle_service.close_cycle(
            db_session, cycle.id, end_date=today_local() - timedelta(days=1),
        )


async def test_route_close_end_before_start_is_422(auth_client, db_session):
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    r = await auth_client.post(
        f"/hrt/cycle/{cycle.id}/close",
        data={"end_date": (today_local() - timedelta(days=5)).isoformat()},
    )
    assert r.status_code == 422
    await db_session.refresh(cycle)
    assert cycle.end_date is None  # nothing was written


async def test_route_add_item_fractional_or_zero_start_week_is_422(auth_client, db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    await auth_client.post(
        "/hrt/cycle", data={"kind": "course", "start_date": today_local().isoformat()},
    )
    cycle = await hrt_cycle_service.active_cycle(db_session)
    for bad_week in ("2.5", "0"):
        r = await auth_client.post(
            f"/hrt/cycle/{cycle.id}/item",
            data={"compound_key": "testosterone_enanthate", "dose": "125",
                  "interval_days": "3.5", "start_week": bad_week},
        )
        assert r.status_code == 422, bad_week
    await db_session.refresh(cycle)
    assert cycle.items == []  # nothing slipped through
