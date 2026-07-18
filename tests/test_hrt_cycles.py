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
def test_expand_flat_fractional_interval():
    seg = [{"dose": 125, "interval_days": 3.5, "duration_days": 14}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=30))
    offsets = [(d - ANCHOR).days for d, _ in adm]
    assert offsets == [0, 4, 7, 10]
    assert {v for _, v in adm} == {125.0}


def test_expand_linear_ramp():
    seg = [{"dose_start": 250, "dose_end": 500, "step": 50, "step_every_days": 7,
            "interval_days": 7, "duration_days": 28}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=45))
    assert [((d - ANCHOR).days, v) for d, v in adm] == [
        (0, 250.0), (7, 300.0), (14, 350.0), (21, 400.0)
    ]


def test_expand_ramp_clamps_to_end():
    seg = [{"dose_start": 200, "dose_end": 300, "step": 100, "step_every_days": 7,
            "interval_days": 7, "duration_days": 28}]
    adm = hrt_cycle_service.expand_schedule(seg, ANCHOR, ANCHOR, ANCHOR + timedelta(days=45))
    doses = [v for _, v in adm]
    assert max(doses) == 300.0  # clamped, never overshoots dose_end


def test_expand_two_segments_blast_then_open_cruise():
    segs = [{"dose": 500, "interval_days": 7, "duration_days": 14},
            {"dose": 150, "interval_days": 7}]
    adm = hrt_cycle_service.expand_schedule(segs, ANCHOR, ANCHOR, ANCHOR + timedelta(days=34))
    assert [((d - ANCHOR).days, v) for d, v in adm] == [
        (0, 500.0), (7, 500.0), (14, 150.0), (21, 150.0), (28, 150.0)
    ]


def test_expand_windows_to_start_end():
    seg = [{"dose": 100, "interval_days": 7}]
    # Only administrations within [ANCHOR+10, ANCHOR+20] returned.
    adm = hrt_cycle_service.expand_schedule(
        seg, ANCHOR, ANCHOR + timedelta(days=10), ANCHOR + timedelta(days=20)
    )
    offsets = [(d - ANCHOR).days for d, _ in adm]
    assert offsets == [14]


def test_expand_empty_schedule():
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
        db_session, kind="cruise", start_date=date(2026, 5, 1),
    )
    await db_session.commit()
    c2 = await hrt_cycle_service.add_cycle(
        db_session, kind="blast", start_date=date(2026, 6, 1),
    )
    await db_session.commit()
    await db_session.refresh(c1)
    assert c1.end_date == date(2026, 5, 31)  # auto-closed the day before c2
    assert c2.end_date is None


async def test_active_cycle_covers_today(db_session):
    await hrt_cycle_service.add_cycle(
        db_session, kind="trt_baseline", start_date=today_local() - timedelta(days=5),
    )
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active is not None and active.kind == "trt_baseline"


async def test_add_item_and_planned_administrations(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="trt_baseline", start_date=today_local(),
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
        db_session, kind="blast", start_date=today_local(),
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
        db_session, kind="blast", start_date=today_local(),
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
        data={"kind": "blast", "name": "Summer", "start_date": today_local().isoformat()},
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
