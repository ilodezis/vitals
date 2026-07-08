"""Timeline service — manual annotation CRUD, the merged event feed (manual +
derived), and per-domain chart overlays."""
from __future__ import annotations

from datetime import date

import pytest

from vitals.enums import AnnotationKind, Domain, MilestoneStatus
from vitals.models.body_scan import DOMAIN as BODY_DOMAIN, BodyScan
from vitals.models.glp1 import DOMAIN as GLP1_DOMAIN, DosePhase
from vitals.models.labs import LabResult
from vitals.models.milestones import Milestone
from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN, NoiseMarker
from vitals.services import timeline_service

pytestmark = pytest.mark.asyncio


async def test_create_update_delete_annotation(db_session):
    row = await timeline_service.create_annotation(
        db_session,
        title="Поездка в Грузию",
        on_date=date(2026, 6, 1),
        end_date=date(2026, 6, 10),
        kind=AnnotationKind.TRAVEL.value,
        domain=Domain.TIMELINE.value,
        note="отпуск",
    )
    await db_session.commit()
    assert row.id is not None
    assert row.kind == "travel"

    fetched = await timeline_service.get_annotation(db_session, row.id)
    assert fetched is not None and fetched.title == "Поездка в Грузию"

    updated = await timeline_service.update_annotation(
        db_session,
        row.id,
        title="Поездка (изменено)",
        on_date=date(2026, 6, 2),
        end_date=None,
        kind=AnnotationKind.LIFE_EVENT.value,
        domain=Domain.WEIGHT.value,
    )
    assert updated is not None
    assert updated.title == "Поездка (изменено)"
    assert updated.end_date is None
    assert updated.domain == Domain.WEIGHT.value

    assert await timeline_service.delete_annotation(db_session, row.id) is True
    assert await timeline_service.get_annotation(db_session, row.id) is None
    assert await timeline_service.delete_annotation(db_session, row.id) is False


async def test_list_annotations_filters_by_domain_and_range(db_session):
    await timeline_service.create_annotation(
        db_session, title="Global", on_date=date(2026, 5, 1), domain=Domain.TIMELINE.value,
    )
    await timeline_service.create_annotation(
        db_session, title="Weight-only", on_date=date(2026, 5, 5), domain=Domain.WEIGHT.value,
    )
    await timeline_service.create_annotation(
        db_session,
        title="Ranged trip",
        on_date=date(2026, 5, 10),
        end_date=date(2026, 5, 20),
        domain=Domain.WEIGHT.value,
    )
    await db_session.commit()

    weight_only = await timeline_service.list_annotations(db_session, domain=Domain.WEIGHT.value)
    assert {a.title for a in weight_only} == {"Weight-only", "Ranged trip"}

    # A point in the middle of the ranged trip should match a range query.
    in_range = await timeline_service.list_annotations(
        db_session, start=date(2026, 5, 15), end=date(2026, 5, 16)
    )
    assert {a.title for a in in_range} == {"Ranged trip"}

    # Newest first.
    all_rows = await timeline_service.list_annotations(db_session)
    assert [a.title for a in all_rows] == ["Ranged trip", "Weight-only", "Global"]


async def test_list_events_merges_manual_and_derived(db_session):
    await timeline_service.create_annotation(
        db_session, title="Болел", on_date=date(2026, 6, 5), kind=AnnotationKind.ILLNESS.value,
    )

    db_session.add(DosePhase(
        domain=GLP1_DOMAIN, start_date=date(2026, 6, 1), drug="semaglutide", dose_mg=0.5,
    ))
    db_session.add(LabResult(
        date=date(2026, 6, 3), domain="labs", source="manual", marker="TSH", value=2.1,
    ))
    db_session.add(LabResult(
        date=date(2026, 6, 3), domain="labs", source="manual", marker="Ferritin", value=90,
    ))
    db_session.add(BodyScan(date=date(2026, 6, 4), domain=BODY_DOMAIN, source="manual", device="InBody 770"))
    m = Milestone(name="Дойти до 85 кг", status=MilestoneStatus.ACHIEVED.value)
    db_session.add(m)
    db_session.add(NoiseMarker(
        domain=WEIGHT_DOMAIN, source="manual", start_date=date(2026, 6, 2),
        end_date=date(2026, 6, 4), reason="загрузка креатином",
    ))
    await db_session.commit()

    events = await timeline_service.list_events(db_session)
    refs = {e.ref for e in events}

    assert any(e.title == "Болел" and e.source == "manual" for e in events)
    assert any("GLP-1" in e.title or "semaglutide" in e.title.lower() for e in events)
    labs_events = [e for e in events if e.domain == "labs"]
    assert len(labs_events) == 1 and "2" in labs_events[0].title
    assert any(e.domain == BODY_DOMAIN for e in events)
    assert any("Дойти до 85 кг" in e.title for e in events)
    assert any(e.domain == WEIGHT_DOMAIN and "noise_marker" in e.ref for e in events)
    assert len(refs) == len(events)  # every ref is unique

    # Sorted newest first.
    dates = [e.date for e in events]
    assert dates == sorted(dates, reverse=True)


async def test_list_events_domain_filter_always_includes_global(db_session):
    await timeline_service.create_annotation(
        db_session, title="Global note", on_date=date(2026, 6, 1), domain=Domain.TIMELINE.value,
    )
    await timeline_service.create_annotation(
        db_session, title="Glp1 note", on_date=date(2026, 6, 1), domain=Domain.GLP1.value,
    )
    await db_session.commit()

    events = await timeline_service.list_events(db_session, domains=[Domain.WEIGHT.value])
    titles = {e.title for e in events}
    assert "Global note" in titles
    assert "Glp1 note" not in titles


async def test_overlays_for_domain_includes_own_and_global_only(db_session):
    await timeline_service.create_annotation(
        db_session, title="Global flag", on_date=date(2026, 6, 1), domain=Domain.TIMELINE.value,
    )
    await timeline_service.create_annotation(
        db_session, title="Weight flag", on_date=date(2026, 6, 5),
        end_date=date(2026, 6, 8), domain=Domain.WEIGHT.value,
    )
    await timeline_service.create_annotation(
        db_session, title="GLP-1 only flag", on_date=date(2026, 6, 1), domain=Domain.GLP1.value,
    )
    await db_session.commit()

    overlays = await timeline_service.overlays_for(db_session, domain=Domain.WEIGHT.value)
    labels = {o["label"] for o in overlays}
    assert labels == {"Global flag", "Weight flag"}

    ranged = next(o for o in overlays if o["label"] == "Weight flag")
    assert ranged["start"] == "2026-06-05"
    assert ranged["end"] == "2026-06-08"

    point = next(o for o in overlays if o["label"] == "Global flag")
    assert point["end"] is None
