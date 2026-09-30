"""The read-path optimisations: what they must keep true, not how fast they are.

* ``read_memo`` — the weight history is read once per unit of work, and a write
  in that unit is always seen by the next read.
* ``AppGZipMiddleware`` — the app's JSON is compressed, server-rendered HTML is not.
* ``exercise_sessions_by_template`` — the batched read equals the per-exercise one.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from sqlalchemy import event

from vitals.enums import Source
from vitals.models.hevy import DOMAIN as HEVY_DOMAIN
from vitals.models.hevy import HevyExercise, HevySet, HevyWorkout
from vitals.models.weight import DOMAIN as WEIGHT_DOMAIN
from vitals.models.weight import WeightLog
from vitals.services import hevy_service, weight_service


def _weight(on: dt.date, kg: float) -> WeightLog:
    return WeightLog(date=on, weight_kg=kg, domain=WEIGHT_DOMAIN, source=Source.MANUAL.value)


@contextmanager
def _selects_from(db_session, table: str):
    seen: list[str] = []
    engine = db_session.bind.sync_engine

    def _on(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and f"FROM {table}" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _on)


async def test_weight_history_is_read_once_per_unit_of_work(db_session):
    db_session.add(_weight(dt.date(2026, 1, 1), 90.0))
    await db_session.commit()
    with _selects_from(db_session, "weight_logs") as seen:
        first = await weight_service.list_active_weights(db_session)
        upto = await weight_service.list_active_weights(db_session, end=dt.date(2026, 1, 1))
        window = await weight_service.list_active_weights(db_session, start=dt.date(2026, 1, 1))

    assert [w.weight_kg for w in first] == [w.weight_kg for w in upto] == [w.weight_kg for w in window] == [90.0]
    assert len(seen) == 1


async def test_a_write_in_the_same_unit_is_seen(db_session):
    db_session.add(_weight(dt.date(2026, 1, 1), 90.0))
    await db_session.commit()
    assert len(await weight_service.list_active_weights(db_session)) == 1

    # Pending (not yet flushed): the memo steps aside and the query autoflushes.
    db_session.add(_weight(dt.date(2026, 1, 2), 89.5))
    assert [w.weight_kg for w in await weight_service.list_active_weights(db_session)] == [90.0, 89.5]

    # Changed in place and flushed: the flush drops the memo.
    rows = await weight_service.list_active_weights(db_session)
    rows[-1].weight_kg = 89.0
    await db_session.flush()
    assert [w.weight_kg for w in await weight_service.list_active_weights(db_session)] == [90.0, 89.0]

    # A write statement drops it too.
    from sqlalchemy import update

    await db_session.execute(update(WeightLog).where(WeightLog.date == dt.date(2026, 1, 2)).values(superseded=True))
    assert [w.weight_kg for w in await weight_service.list_active_weights(db_session)] == [90.0]


async def test_api_json_is_compressed(auth_client, db_session):
    for day in range(40):
        db_session.add(_weight(dt.date(2026, 1, 1) + dt.timedelta(days=day), 90.0 - day / 10))
    await db_session.commit()
    r = await auth_client.get("/api/v1/weight", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "accept-encoding" in r.headers.get("vary", "").lower()
    assert r.json()  # httpx undoes the encoding: the body is intact


async def test_server_rendered_html_is_not_compressed(client):
    r = await client.get("/login", headers={"accept-encoding": "gzip", "accept": "text/html"})
    assert r.status_code == 200
    assert len(r.content) > 1024
    assert "content-encoding" not in r.headers


async def test_batched_exercise_history_matches_the_single_read(db_session):
    for i, (weight, reps) in enumerate([(80.0, 8), (82.5, 6), (85.0, 5)]):
        w = HevyWorkout(domain=HEVY_DOMAIN, source=Source.HEVY_API.value, external_id=f"w{i}", title="Push", date=dt.date(2026, 3, 1) + dt.timedelta(days=i * 3))
        db_session.add(w)
        await db_session.flush()
        for tid, title, bump in (("BENCH", "Bench", 0.0), ("OHP", "Press", -30.0)):
            ex = HevyExercise(workout_id=w.id, exercise_index=0, title=title, exercise_template_id=tid, notes=f"{tid} {i}")
            db_session.add(ex)
            await db_session.flush()
            db_session.add(HevySet(exercise_id=ex.id, set_index=0, set_type="warmup", weight_kg=20.0, reps=10))
            db_session.add(HevySet(exercise_id=ex.id, set_index=1, set_type="normal", weight_kg=weight + bump, reps=reps))
    await db_session.commit()

    batched = await hevy_service.exercise_sessions_by_template(db_session)
    assert set(batched) == {"BENCH", "OHP"}
    for tid in ("BENCH", "OHP"):
        sessions = batched[tid]
        assert hevy_service.series_from_sessions(sessions) == await hevy_service.working_weight_series(db_session, tid)
        assert hevy_service.notes_from_sessions(sessions) == await hevy_service.latest_notes(db_session, tid) == f"{tid} 2"
        # Warm-up sets never count as working sets.
        assert all(s.set_type == "normal" for _, sets, _ in sessions for s in sets)
    assert await hevy_service.exercise_sessions_by_template(db_session, []) == {}
