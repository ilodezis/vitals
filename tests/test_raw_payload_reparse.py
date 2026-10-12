"""Raw-payload reparse sweep.

``upsert_raw_payload`` leaves ``processed_at = None`` whenever it refreshes an
existing row ("re-parse pending"). ``raw_payload_service.sweep_domain`` is the
generic sweep that picks those rows back up; garmin and hevy each wire it in
with their own ``reparse`` callback + ``has_normalized`` clause.

The first group tests ``sweep_domain`` itself, once, generically (using the
Hevy domain/model as the vehicle — any domain would do). The second group is
one smoke test per swept domain, proving its own wiring actually reparses a
payload end to end. The last group pins what the sweep must NOT touch: a lab or
body-scan upload whose preview the owner never confirmed, and the
``reject_upload`` call that closes such a row on Cancel / Skip.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from vitals.enums import Source
from vitals.models.body_scan import BodyScan
from vitals.models.garmin import GarminActivity, GarminDaily
from vitals.models.hevy import HevyWorkout
from vitals.models.labs import LabResult
from vitals.models.raw_payload import RawPayload
from vitals.models.weight import WeightLog
from vitals.utils.timeutils import now_local
from vitals.services import (
    body_scan_service,
    garmin_service,
    hevy_service,
    labs_service,
    raw_payload_service,
)


async def _seed_raw(session, *, domain, source, external_id, payload) -> RawPayload:
    row = RawPayload(domain=domain, source=source, external_id=external_id, payload=payload)
    session.add(row)
    await session.flush()
    return row


def _has_hevy_child():
    return select(HevyWorkout.id).where(HevyWorkout.raw_payload_id == RawPayload.id).exists()


# ── Generic sweep_domain behaviour ────────────────────────────────────────────
async def test_sweep_domain_reparses_a_pending_row_with_no_normalized_child(db_session):
    raw = await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-pending", payload={"ok": True},
    )
    calls = []

    async def _reparse(session, raw_row):
        calls.append(raw_row.id)

    done = await raw_payload_service.sweep_domain(
        db_session, domain=hevy_service.DOMAIN, reparse=_reparse, has_normalized=_has_hevy_child(),
    )
    assert done == 1
    assert calls == [raw.id]
    assert raw.processed_at is not None


async def test_sweep_domain_skips_a_row_that_already_has_a_normalized_child(db_session):
    raw = await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-done", payload={"ok": True},
    )
    db_session.add(HevyWorkout(
        external_id="w-done", domain=hevy_service.DOMAIN, date=date(2026, 6, 10), raw_payload_id=raw.id,
    ))
    await db_session.flush()
    calls = []

    async def _reparse(session, raw_row):
        calls.append(raw_row.id)

    done = await raw_payload_service.sweep_domain(
        db_session, domain=hevy_service.DOMAIN, reparse=_reparse, has_normalized=_has_hevy_child(),
    )
    assert done == 0
    assert calls == []
    assert raw.processed_at is None  # still pending — untouched, not wrongly stamped


async def test_sweep_domain_one_failure_does_not_abort_the_batch(db_session):
    bad = await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-bad", payload={"ok": True},
    )
    good = await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-good", payload={"ok": True},
    )

    async def _reparse(session, raw_row):
        if raw_row.external_id == "w-bad":
            raise ValueError("boom")

    done = await raw_payload_service.sweep_domain(
        db_session, domain=hevy_service.DOMAIN, reparse=_reparse, has_normalized=_has_hevy_child(),
    )
    assert done == 1
    assert bad.processed_at is None  # left pending for the next sweep
    assert good.processed_at is not None


# ── Per-domain wiring smoke tests ─────────────────────────────────────────────
async def test_garmin_reparse_pending_recovers_daily_and_activity(db_session):
    """Garmin is the one domain with two models under an ``or_`` — exercise both
    the ``daily:``/``activity:`` dispatch branches in reparse_from_raw."""
    daily_raw = await _seed_raw(
        db_session, domain=garmin_service.DOMAIN, source=Source.GARMIN_API.value,
        external_id="daily:2026-06-10", payload={"summary": {"totalSteps": 4000}},
    )
    activity_raw = await _seed_raw(
        db_session, domain=garmin_service.DOMAIN, source=Source.GARMIN_API.value,
        external_id="activity:act1", payload={"activityId": "act1", "activityName": "Run"},
    )

    done = await garmin_service.reparse_pending(db_session)
    assert done == 2

    daily = (await db_session.execute(
        select(GarminDaily).where(GarminDaily.date == date(2026, 6, 10))
    )).scalars().first()
    assert daily is not None and daily.raw_payload_id == daily_raw.id and daily.steps == 4000

    activity = (await db_session.execute(
        select(GarminActivity).where(GarminActivity.external_id == "act1")
    )).scalars().first()
    assert activity is not None and activity.raw_payload_id == activity_raw.id


async def test_hevy_reparse_pending_recovers_pending_workout(db_session):
    raw = await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-reparse",
        payload={
            "id": "w-reparse", "title": "Push", "start_time": "2026-06-10T10:00:00Z",
            "updated_at": "2026-06-10T11:00:00Z", "exercises": [],
        },
    )
    done = await hevy_service.reparse_pending(db_session)
    assert done == 1

    workout = (await db_session.execute(
        select(HevyWorkout).where(HevyWorkout.external_id == "w-reparse")
    )).scalars().first()
    assert workout is not None and workout.raw_payload_id == raw.id


# ── Unconfirmed uploads are not swept ─────────────────────────────────────────
_HEVY_PAYLOAD = {
    "id": "w-nightly", "title": "Pull", "start_time": "2026-06-10T10:00:00Z",
    "updated_at": "2026-06-10T11:00:00Z", "exercises": [],
}


async def test_nightly_sweep_leaves_unconfirmed_lab_and_scan_uploads_alone(
    db_session, session_factory
):
    """An upload's raw row is an extraction the owner has not confirmed — a
    preview they cancelled, skipped as misread, or simply closed. The nightly
    sweep used to ingest it anyway: lab values dated today by fallback, and a
    scan weight that outranks Garmin. It must still run for the polled domains."""
    lab_raw = await _seed_raw(
        db_session, domain=labs_service.DOMAIN, source=Source.LAB_PARSER.value,
        external_id="labs/abandoned.png",
        payload={"date": "2026-06-10", "results": [{"marker": "Ferritin", "value": 95}]},
    )
    scan_raw = await _seed_raw(
        db_session, domain=body_scan_service.DOMAIN, source=Source.BODY_SCAN.value,
        external_id="body/abandoned.png",
        payload={
            "date": "2026-06-10", "device": "МедАсс",
            "metrics": [{"label": "Вес", "metric_key": "weight", "value": 84.0, "unit": "кг"}],
        },
    )
    await _seed_raw(
        db_session, domain=hevy_service.DOMAIN, source=Source.HEVY_API.value,
        external_id="w-nightly", payload=_HEVY_PAYLOAD,
    )
    await db_session.commit()

    await raw_payload_service.sweep_pending_job(session_factory)

    assert (await db_session.execute(select(LabResult))).scalars().all() == []
    assert (await db_session.execute(select(BodyScan))).scalars().all() == []
    assert (await db_session.execute(select(WeightLog))).scalars().all() == []
    await db_session.refresh(lab_raw)
    await db_session.refresh(scan_raw)
    assert lab_raw.processed_at is None and scan_raw.processed_at is None
    # The sweep itself did run.
    workout = (await db_session.execute(
        select(HevyWorkout).where(HevyWorkout.external_id == "w-nightly")
    )).scalars().first()
    assert workout is not None


async def test_reject_upload_closes_the_row_and_keeps_the_extraction(db_session):
    raw = await _seed_raw(
        db_session, domain=labs_service.DOMAIN, source=Source.LAB_PARSER.value,
        external_id="labs/cancelled.png",
        payload={"date": "2026-06-10", "results": [{"marker": "TSH", "value": 2.1}]},
    )

    ok = await raw_payload_service.reject_upload(db_session, raw.id, domain=labs_service.DOMAIN)

    assert ok is True
    kept = await db_session.get(RawPayload, raw.id)
    assert kept is not None and kept.processed_at is not None
    assert kept.payload["results"] == [{"marker": "TSH", "value": 2.1}]
    assert raw_payload_service.REJECTED_KEY in kept.payload


async def test_reject_upload_refuses_another_domains_row(db_session):
    raw = await _seed_raw(
        db_session, domain=body_scan_service.DOMAIN, source=Source.BODY_SCAN.value,
        external_id="body/scan.png", payload={"metrics": []},
    )
    ok = await raw_payload_service.reject_upload(db_session, raw.id, domain=labs_service.DOMAIN)
    assert ok is False
    assert raw.processed_at is None
    assert raw_payload_service.REJECTED_KEY not in raw.payload


async def test_reject_upload_leaves_a_confirmed_row_alone(db_session):
    raw = await _seed_raw(
        db_session, domain=labs_service.DOMAIN, source=Source.LAB_PARSER.value,
        external_id="labs/confirmed.png", payload={"results": []},
    )
    stamped = raw.processed_at = now_local()  # what confirming the preview does
    await db_session.flush()

    ok = await raw_payload_service.reject_upload(db_session, raw.id, domain=labs_service.DOMAIN)
    assert ok is False
    assert raw.processed_at == stamped
    assert raw_payload_service.REJECTED_KEY not in raw.payload


async def test_reject_upload_unknown_id_is_false(db_session):
    assert await raw_payload_service.reject_upload(db_session, 987654, domain=labs_service.DOMAIN) is False
