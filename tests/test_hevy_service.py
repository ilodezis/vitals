"""Hevy service tests — sync/normalise, idempotency, re-normalisation on change,
working-weight history, progression verdicts, and the raw-payload safety net."""
from __future__ import annotations

from sqlalchemy import func, select

from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.raw_payload import RawPayload
from vitals.services import hevy_service
from vitals.services.analytics.progression import ADVANCE, DELOAD



class FakeHevyClient:
    """Duck-typed stand-in for HevyClient — returns canned workouts as ``updated``
    events (plus any ``deleted`` ones), no network. Records each ``since`` asked."""

    def __init__(self, workouts, deleted=()):
        self._workouts = workouts
        self._deleted = deleted
        self.is_configured = True
        self.since_calls: list[str] = []

    async def fetch_workout_events(self, *, since: str):
        self.since_calls.append(since)
        return [{"type": "updated", "workout": w} for w in self._workouts] + [
            {"type": "deleted", "id": wid, "deleted_at": at} for wid, at in self._deleted
        ]


def _set(index, weight, reps, type_="normal"):
    return {
        "index": index,
        "type": type_,
        "weight_kg": weight,
        "reps": reps,
        "distance_meters": None,
        "duration_seconds": None,
        "rpe": None,
    }


def _workout(wid, *, start, updated, title="Day A — Push", sets=None, template="BENCH"):
    return {
        "id": wid,
        "title": title,
        "description": "morning session",
        "start_time": start,
        "end_time": start.replace("T10", "T11"),
        "updated_at": updated,
        "exercises": [
            {
                "index": 0,
                "title": "Bench Press (Barbell)",
                "exercise_template_id": template,
                "notes": "elbows tucked",
                "superset_id": None,
                "sets": sets or [_set(0, 80.0, 10), _set(1, 80.0, 9)],
            }
        ],
    }


async def test_sync_creates_workout_tree(db_session):
    client = FakeHevyClient(
        [_workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")]
    )
    summary = await hevy_service.sync(db_session, client)
    await db_session.commit()

    assert summary == {
        "fetched": 1, "created": 1, "updated": 0, "deleted": 0, "skipped": 0,
        "full": True, "total": 1,
    }

    workouts = await hevy_service.list_workouts(db_session)
    assert len(workouts) == 1
    w = workouts[0]
    assert w.external_id == "w1"
    assert w.program == "A"  # "Day A" → A
    assert w.title == "Bench Press (Barbell)" or w.title == "Day A — Push"
    assert len(w.exercises) == 1
    assert w.exercises[0].exercise_template_id == "BENCH"
    assert len(w.exercises[0].sets) == 2

    # Raw payload preserved + linked + marked processed.
    raw = (await db_session.execute(select(RawPayload))).scalars().all()
    assert len(raw) == 1
    assert raw[0].external_id == "w1"
    assert raw[0].processed_at is not None
    assert w.raw_payload_id == raw[0].id


async def test_sync_idempotent_skips_unchanged(db_session):
    wk = _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")
    client = FakeHevyClient([wk])

    await hevy_service.sync(db_session, client)
    await db_session.commit()
    summary2 = await hevy_service.sync(db_session, client)
    await db_session.commit()

    assert summary2["skipped"] == 1
    assert summary2["created"] == 0
    assert await hevy_service.workout_count(db_session) == 1


async def test_sync_renormalises_changed_workout_without_orphans(db_session):
    wk = _workout(
        "w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z",
        sets=[_set(0, 80.0, 10), _set(1, 80.0, 10)],
    )
    await hevy_service.sync(db_session, FakeHevyClient([wk]), )
    await db_session.commit()

    # Same id, newer updated_at, different sets → re-normalised in place.
    wk2 = _workout(
        "w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T12:30:00Z",
        sets=[_set(0, 82.5, 8)],
    )
    summary = await hevy_service.sync(db_session, FakeHevyClient([wk2]))
    await db_session.commit()

    assert summary["updated"] == 1
    assert await hevy_service.workout_count(db_session) == 1
    # No orphaned exercises/sets — exactly one exercise + one set remain.
    n_ex = (await db_session.execute(select(func.count()).select_from(HevyExercise))).scalar()
    n_set = (await db_session.execute(select(func.count()).select_from(HevySet))).scalar()
    assert n_ex == 1
    assert n_set == 1
    # One raw payload, refreshed in place (not duplicated).
    n_raw = (await db_session.execute(select(func.count()).select_from(RawPayload))).scalar()
    assert n_raw == 1


async def test_working_weight_series_and_catalog(db_session):
    client = FakeHevyClient(
        [
            _workout("w1", start="2026-06-01T10:00:00Z", updated="2026-06-01T11:00:00Z",
                     sets=[_set(0, 80.0, 10)]),
            _workout("w2", start="2026-06-08T10:00:00Z", updated="2026-06-08T11:00:00Z",
                     sets=[_set(0, 82.5, 8)]),
        ]
    )
    await hevy_service.sync(db_session, client)
    await db_session.commit()

    series = await hevy_service.working_weight_series(db_session, "BENCH")
    assert [p["weight_kg"] for p in series] == [80.0, 82.5]
    assert series[0]["date"] == "2026-06-01"

    catalog = await hevy_service.exercise_catalog(db_session)
    assert len(catalog) == 1
    assert catalog[0]["exercise_template_id"] == "BENCH"
    assert catalog[0]["sessions"] == 2


async def test_progression_advance_when_top_of_range_hit(db_session):
    from vitals.services.analytics.progression import ProgressionConfig

    client = FakeHevyClient(
        [
            _workout("w1", start="2026-06-08T10:00:00Z", updated="2026-06-08T11:00:00Z",
                     sets=[_set(0, 80.0, 12), _set(1, 80.0, 12), _set(2, 80.0, 12)]),
        ]
    )
    await hevy_service.sync(db_session, client)
    await db_session.commit()

    verdict = await hevy_service.progression_for_exercise(
        db_session, "BENCH", ProgressionConfig(rep_min=8, rep_max=12, increment_kg=2.5)
    )
    assert verdict is not None
    assert verdict.status == ADVANCE
    assert verdict.suggested_weight_kg == 82.5


async def test_workout_without_id_is_skipped(db_session):
    client = FakeHevyClient([{"id": "", "exercises": []}])
    summary = await hevy_service.sync(db_session, client)
    await db_session.commit()
    assert summary["skipped"] == 1
    assert await hevy_service.workout_count(db_session) == 0


# ── Incremental sync over the event feed ──────────────────────────────────────

from datetime import datetime, timedelta, timezone

import pytest

from vitals.models.app_settings import AppSetting


async def _since(db_session):
    row = await db_session.get(AppSetting, hevy_service.SYNC_SINCE_KEY)
    return row.value if row is not None else None


async def test_first_sync_reads_from_the_epoch_and_later_ones_from_the_mark(db_session):
    client = FakeHevyClient(
        [_workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")]
    )
    first = await hevy_service.sync(db_session, client)
    await db_session.commit()
    assert first["full"] is True
    assert client.since_calls == ["1970-01-01T00:00:00Z"]

    mark = await _since(db_session)
    assert mark is not None
    # A day behind the pass, so skew between the clocks never drops an event.
    lag = datetime.now(timezone.utc) - datetime.fromisoformat(mark.replace("Z", "+00:00"))
    assert timedelta(hours=23) < lag < timedelta(hours=25)

    second = await hevy_service.sync(db_session, client)
    await db_session.commit()
    assert second["full"] is False
    assert client.since_calls[-1] == mark
    assert second["skipped"] == 1


async def test_force_reads_the_whole_feed_again(db_session):
    client = FakeHevyClient(
        [_workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")]
    )
    await hevy_service.sync(db_session, client)
    await db_session.commit()

    summary = await hevy_service.sync(db_session, client, force=True)
    assert summary["full"] is True
    assert client.since_calls[-1] == "1970-01-01T00:00:00Z"
    assert summary["updated"] == 1  # force re-normalises even an unchanged workout


async def test_a_failed_pass_does_not_move_the_mark(db_session, monkeypatch):
    """The mark is written with the last workout, in the same transaction: a pass
    that dies halfway must be read again, not skipped past."""
    client = FakeHevyClient([
        _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z"),
        _workout("w2", start="2026-06-11T10:00:00Z", updated="2026-06-11T11:00:00Z"),
    ])
    real_upsert = hevy_service._upsert_workout

    async def upsert_then_fail(session, raw, *, raw_payload_id):
        if raw["id"] == "w2":
            raise RuntimeError("database hiccup")
        return await real_upsert(session, raw, raw_payload_id=raw_payload_id)

    monkeypatch.setattr(hevy_service, "_upsert_workout", upsert_then_fail)
    with pytest.raises(RuntimeError):
        await hevy_service.sync(db_session, client)
    await db_session.rollback()

    assert await _since(db_session) is None
    assert await hevy_service.workout_count(db_session) == 0


async def test_workout_deleted_in_hevy_is_removed_and_stays_removed(db_session):
    wk = _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")
    keep = _workout("w2", start="2026-06-11T10:00:00Z", updated="2026-06-11T11:00:00Z")
    await hevy_service.sync(db_session, FakeHevyClient([wk, keep]))
    await db_session.commit()
    # Read the tree into the session first: the delete must not trip over it.
    assert len(await hevy_service.list_workouts(db_session)) == 2

    summary = await hevy_service.sync(
        db_session, FakeHevyClient([], deleted=[("w1", "2026-06-12T09:00:00Z")])
    )
    await db_session.commit()

    assert summary["deleted"] == 1
    assert summary["total"] == 1
    assert [w.external_id for w in await hevy_service.list_workouts(db_session)] == ["w2"]
    assert (await db_session.execute(select(func.count()).select_from(HevyExercise))).scalar() == 1
    assert (await db_session.execute(select(func.count()).select_from(HevySet))).scalar() == 2

    # The payload is kept, stamped processed — the nightly sweep must not rebuild it.
    raw = (
        await db_session.execute(select(RawPayload).where(RawPayload.external_id == "w1"))
    ).scalars().one()
    assert raw.processed_at is not None
    assert await hevy_service.reparse_pending(db_session) == 0
    await db_session.commit()
    assert await hevy_service.workout_count(db_session) == 1


async def test_deleted_workout_with_pending_payload_is_not_resurrected(db_session):
    """A payload refreshed but not yet processed is exactly what the sweep picks
    up; deleting its workout must close it."""
    wk = _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-10T11:00:00Z")
    await hevy_service.sync(db_session, FakeHevyClient([wk]))
    raw = (await db_session.execute(select(RawPayload))).scalars().one()
    raw.processed_at = None
    await db_session.commit()

    await hevy_service.sync(db_session, FakeHevyClient([], deleted=[("w1", "2026-06-12T09:00:00Z")]))
    await db_session.commit()

    assert await hevy_service.reparse_pending(db_session) == 0
    assert await hevy_service.workout_count(db_session) == 0


@pytest.mark.parametrize("deleted_at, survives", [
    ("2026-06-12T09:00:00Z", False),   # deleted after the last edit
    ("2026-06-10T09:00:00Z", True),    # an old delete, the workout came back after
])
async def test_newest_event_per_workout_wins(db_session, deleted_at, survives):
    wk = _workout("w1", start="2026-06-10T10:00:00Z", updated="2026-06-11T11:00:00Z")
    summary = await hevy_service.sync(db_session, FakeHevyClient([wk], deleted=[("w1", deleted_at)]))
    await db_session.commit()
    assert (await hevy_service.workout_count(db_session) == 1) is survives
    assert summary["fetched"] == 2


async def test_delete_for_a_workout_never_imported_is_a_skip(db_session):
    summary = await hevy_service.sync(
        db_session, FakeHevyClient([], deleted=[("ghost", "2026-06-12T09:00:00Z")])
    )
    assert summary["deleted"] == 0
    assert summary["skipped"] == 1


async def test_client_walks_every_page_of_the_feed(monkeypatch):
    """The old walk stopped at 50 pages — 500 workouts — and dropped the rest."""
    from vitals.integrations.hevy_client import HevyClient

    asked = []

    async def page(self, *, since, page=1, page_size=10):
        asked.append((since, page))
        return {
            "page": page,
            "page_count": 60,
            "events": [{"type": "deleted", "id": f"w{page}", "deleted_at": "2026-01-01T00:00:00Z"}],
        }

    monkeypatch.setattr(HevyClient, "fetch_workout_events_page", page)
    events = await HevyClient().fetch_workout_events(since="1970-01-01T00:00:00Z")
    assert len(events) == 60
    assert asked[0] == ("1970-01-01T00:00:00Z", 1)
    assert asked[-1][1] == 60
