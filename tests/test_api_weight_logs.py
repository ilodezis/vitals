"""``/api/v1/weight/logs`` — what the weight stepper on Today (and the log sheet) writes.

The same service calls as the form on ``/weight/log``; what changes is the shape of
the answer. A blocked write is a 409 carrying the rules it tripped, and repeating
it with ``override`` saves it — the owner always has the last word.
"""
from datetime import timedelta

from sqlalchemy import select

from vitals.enums import Source
from vitals.models.conflict_rule import ConflictRule
from vitals.models.system_alert import SystemAlert
from vitals.models.weight import WeightLog
from vitals.services import weight_service
from vitals.utils.timeutils import today_local

LOGS = "/api/v1/weight/logs"


def _body(**extra):
    return {"date": today_local().isoformat(), "weight_kg": 86.1, **extra}


async def _all(db_session):
    return (await db_session.execute(select(WeightLog).order_by(WeightLog.id))).scalars().all()


async def _block_every_weight(db_session, message="Simulated weight block"):
    db_session.add(
        ConflictRule(
            domain_a="weight", domain_b="weight", condition_a={}, condition_b={},
            rule_type="hard_block", severity="block", message=message, active=True,
        )
    )
    await db_session.commit()


# ── POST ─────────────────────────────────────────────────────────────────────


async def test_the_writes_are_guarded(client):
    for method, url in (("post", LOGS), ("patch", f"{LOGS}/1"), ("delete", f"{LOGS}/1")):
        r = await getattr(client, method)(url, **({"json": _body()} if method != "delete" else {}))
        assert r.status_code == 401, method
        assert r.json() == {"error": "unauthenticated"}


async def test_a_weight_is_created(auth_client, db_session):
    r = await auth_client.post(LOGS, json=_body(note="утром"))

    assert r.status_code == 201
    saved = (await _all(db_session))[0]
    assert r.json() == {"id": saved.id, "created": True}
    assert (saved.weight_kg, saved.note, saved.source) == (86.1, "утром", Source.MANUAL.value)
    assert saved.date == today_local()


async def test_saving_the_same_reading_again_is_not_a_second_row(auth_client, db_session):
    """The service recognises a repeat and hands back the row that is already
    there — the answer says so, so the screen never offers "Undo" for a row the
    owner did not just make."""
    first = (await auth_client.post(LOGS, json=_body())).json()

    again = await auth_client.post(LOGS, json=_body())

    assert again.status_code == 201
    assert again.json() == {"id": first["id"], "created": False}
    assert len(await _all(db_session)) == 1


async def test_a_manual_weight_outranks_garmins_for_the_day(auth_client, db_session):
    """The priority rule is the service's and this route does not touch it."""
    await weight_service.log_weight(
        db_session, on_date=today_local(), weight_kg=86.9, source=Source.GARMIN_API.value
    )
    await db_session.commit()

    await auth_client.post(LOGS, json=_body(weight_kg=86.1))

    rows = {r.source: r for r in await _all(db_session)}
    assert rows[Source.MANUAL.value].superseded is False
    assert rows[Source.GARMIN_API.value].superseded is True


async def test_an_implausible_weight_is_a_400(auth_client, db_session):
    r = await auth_client.post(LOGS, json=_body(weight_kg=900))

    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "invalid"
    assert "weight_kg" in body["message"]
    assert await _all(db_session) == []


async def test_a_malformed_body_is_a_422(auth_client):
    r = await auth_client.post(LOGS, json={"date": "not-a-date", "weight_kg": "heavy"})
    assert r.status_code == 422


async def test_a_blocked_weight_is_a_409_with_its_rules(auth_client, db_session):
    await _block_every_weight(db_session)

    r = await auth_client.post(LOGS, json=_body())

    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "conflict"
    assert body["violations"][0]["message"] == "Simulated weight block"
    assert body["violations"][0]["severity"] == "block"
    assert await _all(db_session) == []


async def test_override_keeps_a_blocked_weight_and_stamps_it(auth_client, db_session):
    await _block_every_weight(db_session)

    r = await auth_client.post(LOGS, json=_body(override=True))

    assert r.status_code == 201
    assert len(await _all(db_session)) == 1
    alerts = (await db_session.execute(select(SystemAlert))).scalars().all()
    assert alerts and alerts[0].override_at is not None


# ── PATCH ────────────────────────────────────────────────────────────────────


async def test_a_weight_is_corrected_in_place(auth_client, db_session):
    row = await weight_service.log_weight(
        db_session, on_date=today_local(), weight_kg=86.1, note="утром"
    )
    await db_session.commit()

    r = await auth_client.patch(f"{LOGS}/{row.id}", json={"weight_kg": 85.7})

    assert r.status_code == 200
    assert r.json() == {"id": row.id}
    await db_session.refresh(row)
    # Only what was sent changes: the date and the note stay.
    assert (row.weight_kg, row.note, row.date) == (85.7, "утром", today_local())


async def test_a_note_can_be_cleared_by_sending_null(auth_client, db_session):
    row = await weight_service.log_weight(
        db_session, on_date=today_local(), weight_kg=86.1, note="утром"
    )
    await db_session.commit()

    await auth_client.patch(f"{LOGS}/{row.id}", json={"note": None})

    await db_session.refresh(row)
    assert row.note is None and row.weight_kg == 86.1


async def test_correcting_a_weight_into_a_block_is_a_409(auth_client, db_session):
    row = await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()
    await _block_every_weight(db_session)

    r = await auth_client.patch(f"{LOGS}/{row.id}", json={"weight_kg": 80.0})

    assert r.status_code == 409
    assert r.json()["error"] == "conflict"
    await db_session.refresh(row)
    assert row.weight_kg == 86.1


async def test_correcting_a_weight_that_is_not_there_is_a_404(auth_client):
    r = await auth_client.patch(f"{LOGS}/9999", json={"weight_kg": 85.0})
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


async def test_moving_a_weight_to_another_day(auth_client, db_session):
    row = await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()
    yesterday = today_local() - timedelta(days=1)

    r = await auth_client.patch(f"{LOGS}/{row.id}", json={"date": yesterday.isoformat()})

    assert r.status_code == 200
    rows = await _all(db_session)
    assert [(x.date, x.weight_kg) for x in rows] == [(yesterday, 86.1)]
    assert r.json() == {"id": rows[0].id}


# ── DELETE ───────────────────────────────────────────────────────────────────


async def test_a_weight_is_deleted(auth_client, db_session):
    row = await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()

    r = await auth_client.delete(f"{LOGS}/{row.id}")

    assert r.status_code == 204
    assert await _all(db_session) == []


async def test_deleting_a_manual_weight_brings_garmins_back(auth_client, db_session):
    """Undo of a weigh-in must hand the day back to the reading it had outranked."""
    await weight_service.log_weight(
        db_session, on_date=today_local(), weight_kg=86.9, source=Source.GARMIN_API.value
    )
    manual = await weight_service.log_weight(db_session, on_date=today_local(), weight_kg=86.1)
    await db_session.commit()

    await auth_client.delete(f"{LOGS}/{manual.id}")

    (garmin,) = await _all(db_session)
    assert garmin.source == Source.GARMIN_API.value and garmin.superseded is False


async def test_deleting_a_weight_that_is_not_there_is_a_404(auth_client):
    r = await auth_client.delete(f"{LOGS}/9999")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}
