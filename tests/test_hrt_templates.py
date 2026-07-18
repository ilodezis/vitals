"""HRT cycle-template tests — save/apply (layer 2) and the portable JSON
export/import share flow (layer 3)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from vitals.services import (
    hrt_catalog,
    hrt_cycle_service,
    hrt_template_service,
)
from vitals.utils.timeutils import today_local

pytestmark = pytest.mark.asyncio


async def _build_staggered_cycle(db_session):
    """A realistic week-anchored course: test wk 1-13, winstrol wk 5-9."""
    await hrt_catalog.sync_catalog(db_session)
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(), name="Cut stack",
    )
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="testosterone_enanthate",
        schedule=[{"dose": 250, "interval_days": 3.5, "duration_days": 91}],
    )
    await hrt_cycle_service.add_cycle_item(
        db_session, cycle.id, compound_key="stanozolol_oral",
        schedule=[{"dose": 30, "interval_days": 1, "duration_days": 28}],
        start_offset_days=28,
    )
    await db_session.commit()
    return cycle


# ── Save as template ──────────────────────────────────────────────────────────
async def test_save_cycle_as_template_snapshots_items(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Cut v1",
    )
    await db_session.commit()
    await db_session.refresh(template)
    assert template.name == "Cut v1" and template.kind == "course"
    assert len(template.items) == 2
    by_key = {it.compound_key: it for it in template.items}
    assert by_key["stanozolol_oral"].start_offset_days == 28
    assert by_key["testosterone_enanthate"].schedule[0]["dose"] == 250


async def test_save_template_requires_name_and_items(db_session):
    cycle = await hrt_cycle_service.add_cycle(
        db_session, kind="course", start_date=today_local(),
    )
    await db_session.commit()
    with pytest.raises(ValueError):
        await hrt_template_service.save_cycle_as_template(
            db_session, cycle.id, name="   ",
        )
    with pytest.raises(ValueError):  # no items on the cycle
        await hrt_template_service.save_cycle_as_template(
            db_session, cycle.id, name="Empty",
        )


async def test_template_survives_cycle_deletion(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Keeper",
    )
    await db_session.commit()
    await hrt_cycle_service.delete_cycle(db_session, cycle.id)
    await db_session.commit()
    kept = await hrt_template_service.get_template(db_session, template.id)
    assert kept is not None and len(kept.items) == 2


# ── Create cycle from template ────────────────────────────────────────────────
async def test_create_cycle_from_template_materializes_plan(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Cut v1",
    )
    await db_session.commit()
    start = today_local() + timedelta(days=30)
    new_cycle = await hrt_template_service.create_cycle_from_template(
        db_session, template.id, start_date=start,
    )
    await db_session.commit()
    await db_session.refresh(new_cycle)
    assert new_cycle.kind == "course" and new_cycle.start_date == start
    assert new_cycle.name == "Cut v1"  # falls back to the template name
    assert len(new_cycle.items) == 2
    by_key = {it.compound_key: it for it in new_cycle.items}
    assert by_key["stanozolol_oral"].start_offset_days == 28
    # Items resolve against the local catalog on apply.
    assert by_key["testosterone_enanthate"].compound_id is not None


async def test_create_from_template_closes_open_cycle(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Next",
    )
    await db_session.commit()
    new_cycle = await hrt_template_service.create_cycle_from_template(
        db_session, template.id, start_date=today_local() + timedelta(days=7),
    )
    await db_session.commit()
    await db_session.refresh(cycle)
    assert cycle.end_date is not None  # the old open cycle got auto-closed
    assert new_cycle.end_date is None


async def test_delete_template_cascades_items(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Gone",
    )
    await db_session.commit()
    assert await hrt_template_service.delete_template(db_session, template.id) is True
    await db_session.commit()
    assert await hrt_template_service.get_template(db_session, template.id) is None


# ── Export / import (share) ───────────────────────────────────────────────────
async def test_export_is_date_free_and_versioned(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Cut v1",
    )
    await db_session.commit()
    await db_session.refresh(template)
    payload = hrt_template_service.export_template(template)
    assert payload["format"] == hrt_template_service.EXPORT_FORMAT
    assert payload["version"] == hrt_template_service.EXPORT_VERSION
    assert "start_date" not in json.dumps(payload)  # relative only, no dates
    assert {it["compound_key"] for it in payload["items"]} == {
        "testosterone_enanthate", "stanozolol_oral",
    }


async def test_import_round_trip(db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Cut v1",
    )
    await db_session.commit()
    await db_session.refresh(template)
    shared = hrt_template_service.export_template_json(template)

    imported = await hrt_template_service.import_template(db_session, shared)
    await db_session.commit()
    await db_session.refresh(imported)
    assert imported.id != template.id
    assert imported.name == "Cut v1" and imported.kind == "course"
    by_key = {it.compound_key: it for it in imported.items}
    assert by_key["stanozolol_oral"].start_offset_days == 28
    assert by_key["testosterone_enanthate"].schedule[0]["interval_days"] == 3.5


async def test_import_rejects_garbage_and_wrong_envelope(db_session):
    with pytest.raises(ValueError, match="JSON"):
        await hrt_template_service.import_template(db_session, "not json {")
    with pytest.raises(ValueError, match="format"):
        await hrt_template_service.import_template(db_session, {"format": "other"})
    with pytest.raises(ValueError, match="version"):
        await hrt_template_service.import_template(
            db_session,
            {"format": hrt_template_service.EXPORT_FORMAT, "version": 99,
             "name": "X", "kind": "course", "items": [{}]},
        )


async def test_import_rejects_unknown_compound_key(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    payload = {
        "format": hrt_template_service.EXPORT_FORMAT, "version": 1,
        "name": "Sketchy", "kind": "course",
        "items": [{"compound_key": "not_a_real_compound",
                   "schedule": [{"dose": 10, "interval_days": 1}]}],
    }
    with pytest.raises(ValueError, match="not_a_real_compound"):
        await hrt_template_service.import_template(db_session, payload)


async def test_import_rejects_bad_kind_offset_and_schedule(db_session):
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    base = {
        "format": hrt_template_service.EXPORT_FORMAT, "version": 1,
        "name": "X",
        "items": [{"compound_key": "oxandrolone",
                   "schedule": [{"dose": 10, "interval_days": 1}]}],
    }
    with pytest.raises(ValueError, match="kind"):
        await hrt_template_service.import_template(db_session, {**base, "kind": "yolo"})
    bad_offset = {**base, "kind": "course", "items": [
        {**base["items"][0], "start_offset_days": -3}
    ]}
    with pytest.raises(ValueError, match="start_offset_days"):
        await hrt_template_service.import_template(db_session, bad_offset)
    bad_schedule = {**base, "kind": "course", "items": [
        {"compound_key": "oxandrolone", "schedule": [{"dose": -5, "interval_days": 1}]}
    ]}
    with pytest.raises(ValueError, match="positive"):
        await hrt_template_service.import_template(db_session, bad_schedule)


async def test_import_normalizes_schedule_via_validator(db_session):
    """Pasted JSON can carry junk keys — the stored schedule keeps known keys only."""
    await hrt_catalog.sync_catalog(db_session)
    await db_session.commit()
    payload = {
        "format": hrt_template_service.EXPORT_FORMAT, "version": 1,
        "name": "Clean", "kind": "pct",
        "items": [{"compound_key": "tamoxifen",
                   "schedule": [{"dose": 20, "interval_days": 1,
                                 "duration_days": 14, "evil": "<script>"}]}],
    }
    imported = await hrt_template_service.import_template(db_session, payload)
    await db_session.commit()
    await db_session.refresh(imported)
    assert imported.items[0].schedule == [
        {"dose": 20.0, "interval_days": 1.0, "duration_days": 14}
    ]


# ── Route-level flows ─────────────────────────────────────────────────────────
async def test_route_save_and_apply_template(auth_client, db_session):
    cycle = await _build_staggered_cycle(db_session)
    r = await auth_client.post(
        f"/hrt/cycle/{cycle.id}/save-template", data={"name": "UI template"},
    )
    assert r.status_code == 303
    templates = await hrt_template_service.list_templates(db_session)
    assert [tp.name for tp in templates] == ["UI template"]

    start = (today_local() + timedelta(days=14)).isoformat()
    r = await auth_client.post(
        f"/hrt/template/{templates[0].id}/create-cycle", data={"start_date": start},
    )
    assert r.status_code == 303
    page = await auth_client.get("/hrt")
    assert "UI template" in page.text


async def test_route_export_download_and_import(auth_client, db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Shared",
    )
    await db_session.commit()

    r = await auth_client.get(f"/hrt/template/{template.id}/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    payload = r.json()
    assert payload["format"] == hrt_template_service.EXPORT_FORMAT

    r = await auth_client.post(
        "/hrt/template/import", data={"payload": json.dumps(payload)},
    )
    assert r.status_code == 303
    names = [tp.name for tp in await hrt_template_service.list_templates(db_session)]
    assert names.count("Shared") == 2  # original + imported copy


async def test_route_import_invalid_payload_is_422(auth_client):
    r = await auth_client.post("/hrt/template/import", data={"payload": "{{nope"})
    assert r.status_code == 422
    assert "error" in r.json()


async def test_route_template_rendered_on_dashboard(auth_client, db_session):
    cycle = await _build_staggered_cycle(db_session)
    await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Visible name",
    )
    await db_session.commit()
    page = await auth_client.get("/hrt")
    assert "Visible name" in page.text
    assert hrt_template_service.EXPORT_FORMAT in page.text  # share code textarea


# ── Fix pack: 404 export, same-day supersede, garbage date ────────────────────
async def test_route_export_missing_template_is_404(auth_client):
    r = await auth_client.get("/hrt/template/99999/export")
    assert r.status_code == 404


async def test_create_from_template_same_day_supersedes(db_session):
    """Applying a template on the active cycle's own start date must win the
    active_cycle tie-break, exactly like a hand-built same-day cycle."""
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="Same day",
    )
    await db_session.commit()
    new_cycle = await hrt_template_service.create_cycle_from_template(
        db_session, template.id, start_date=cycle.start_date,
    )
    await db_session.commit()
    active = await hrt_cycle_service.active_cycle(db_session)
    assert active.id == new_cycle.id
    await db_session.refresh(cycle)
    assert cycle.end_date == cycle.start_date  # clamped, not inverted


async def test_route_create_from_template_garbage_date_is_422(auth_client, db_session):
    cycle = await _build_staggered_cycle(db_session)
    template = await hrt_template_service.save_cycle_as_template(
        db_session, cycle.id, name="T",
    )
    await db_session.commit()
    r = await auth_client.post(
        f"/hrt/template/{template.id}/create-cycle", data={"start_date": "31-12-2026"},
    )
    assert r.status_code == 422
    assert "invalid date" in r.json()["error"]
