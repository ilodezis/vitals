"""Outbound Garmin weight sync: opt-in, idempotency and ownership safety."""
from __future__ import annotations

import asyncio
import importlib
from datetime import date, datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vitals.config import Config
from vitals.enums import Source
from vitals.integrations.garmin_client import GarminClient
from vitals.models.garmin import (
    WEIGHT_EXPORT_CHECKING,
    WEIGHT_EXPORT_CONFLICT,
    WEIGHT_EXPORT_DELETED,
    WEIGHT_EXPORT_DELETE_FAILED,
    WEIGHT_EXPORT_DELETE_PENDING,
    WEIGHT_EXPORT_FAILED,
    WEIGHT_EXPORT_MATCHED,
    WEIGHT_EXPORT_PENDING,
    WEIGHT_EXPORT_SENT,
    WEIGHT_EXPORT_SKIPPED,
    WEIGHT_EXPORT_UNVERIFIED,
    GarminWeightExport,
)
from vitals.models.weight import WeightLog
from vitals.services import (
    alerts_service,
    garmin_service,
    garmin_weight_service,
    weight_service,
)
from vitals.services.proactive import prefs

DAY = date(2026, 8, 15)
NOW = datetime(2026, 8, 15, 9, 30)


class FakeWeightClient:
    def __init__(
        self,
        rows=None,
        *,
        fail_fetch: Exception | None = None,
        response_has_sample_pk: bool = True,
        include_correlation_fields: bool = False,
    ):
        self.rows: dict[date, list[dict]] = {DAY: list(rows or [])}
        self.fail_fetch = fail_fetch
        self.fail_readback: Exception | None = None
        self.response_has_sample_pk = response_has_sample_pk
        self.include_correlation_fields = include_correlation_fields
        self.fetch_calls: list[date] = []
        self.add_calls: list[tuple[float, datetime]] = []
        self.delete_calls: list[tuple[str, date]] = []
        self._next_id = 100
        self.raise_after_add: Exception | None = None
        self.fail_delete: Exception | None = None

    async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
        self.fetch_calls.append(on_date)
        if self.fail_fetch is not None:
            raise self.fail_fetch
        if self.fail_readback is not None and self.add_calls:
            raise self.fail_readback
        return {
            "dateWeightList": [
                dict(row) if isinstance(row, dict) else row
                for row in self.rows.get(on_date, [])
            ]
        }

    async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
        self.add_calls.append((weight_kg, measured_at))
        sample_pk = str(self._next_id)
        self._next_id += 1
        remote = {"samplePk": sample_pk, "weight": weight_kg * 1000}
        if self.include_correlation_fields:
            remote.update(
                {
                    "sourceType": "MANUAL",
                    "timestampGMT": garmin_weight_service._dispatch_timestamp_ms(
                        measured_at
                    ),
                }
            )
        self.rows.setdefault(measured_at.date(), []).append(remote)
        if self.raise_after_add is not None:
            raise self.raise_after_add
        # Pinned garminconnect commonly returns None for this 204 endpoint.
        return {"samplePk": sample_pk} if self.response_has_sample_pk else None

    async def delete_weigh_in(self, sample_pk: str, on_date: date):
        self.delete_calls.append((sample_pk, on_date))
        if self.fail_delete is not None:
            raise self.fail_delete
        self.rows[on_date] = [
            row
            for row in self.rows.get(on_date, [])
            if str(row.get("samplePk")) != str(sample_pk)
        ]


async def _manual_weight(db_session, value: float, *, on_date: date = DAY):
    return await weight_service.log_weight(
        db_session,
        on_date=on_date,
        weight_kg=value,
        source=Source.MANUAL.value,
    )


async def _outbox(
    db_session, *, on_date: date = DAY
) -> GarminWeightExport:
    return (
        await db_session.execute(
            select(GarminWeightExport).where(GarminWeightExport.date == on_date)
        )
    ).scalar_one()


async def test_export_is_opt_in_and_enabling_only_queues_locally(db_session):
    await _manual_weight(db_session, 84.5)

    assert await garmin_weight_service.is_enabled(db_session) is False
    assert (await db_session.execute(select(GarminWeightExport))).scalar_one_or_none() is None

    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    row = await _outbox(db_session)
    assert await garmin_weight_service.is_enabled(db_session) is True
    assert row.status == WEIGHT_EXPORT_PENDING
    assert row.weight_kg == 84.5
    assert row.weight_log_id is not None


async def test_latest_weight_posts_once_then_stays_idempotent(db_session):
    await _manual_weight(db_session, 85.0, on_date=DAY - timedelta(days=1))
    latest = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()

    first = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    second = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert first == {"status": WEIGHT_EXPORT_SENT, "sent": True, "date": DAY}
    assert second == {"status": WEIGHT_EXPORT_SENT, "sent": False, "date": DAY}
    assert len(client.add_calls) == 1
    assert client.add_calls[0][0] == 84.5
    dispatched_at = client.add_calls[0][1]
    assert dispatched_at.replace(second=0, microsecond=0) == NOW
    assert dispatched_at.microsecond % 1000 == 0
    assert dispatched_at.microsecond != 0
    row = await _outbox(db_session)
    assert row.weight_log_id == latest.id
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"
    assert (
        await db_session.execute(select(func.count()).select_from(GarminWeightExport))
    ).scalar_one() == 1


async def test_equal_preexisting_garmin_weight_skips_post_and_is_not_owned(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient([{"samplePk": 77, "weight": 84500}])

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result["sent"] is False
    assert client.add_calls == []
    row = await _outbox(db_session)
    assert row.status == WEIGHT_EXPORT_MATCHED
    assert row.remote_sample_pk == "77"
    assert row.remote_owned is False


async def test_same_day_correction_replaces_only_vitals_owned_record(db_session):
    await _manual_weight(db_session, 85.0)
    client = FakeWeightClient()
    await garmin_weight_service.export_latest(db_session, client, now=NOW)

    await _manual_weight(db_session, 84.0)
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1)
    )

    assert result["sent"] is True
    assert client.delete_calls == [("100", DAY)]
    assert [row["weight"] for row in client.rows[DAY]] == [84000.0]
    row = await _outbox(db_session)
    assert row.remote_owned is True
    assert row.remote_sample_pk == "101"
    assert row.weight_kg == 84.0


async def test_correction_never_deletes_matching_record_vitals_did_not_create(db_session):
    await _manual_weight(db_session, 85.0)
    client = FakeWeightClient([{"samplePk": "external", "weight": 85000}])
    await garmin_weight_service.export_latest(db_session, client, now=NOW)

    await _manual_weight(db_session, 84.0)
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1)
    )

    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert client.delete_calls == []
    assert client.add_calls == []
    assert [row["weight"] for row in client.rows[DAY]] == [85000]


async def test_accepted_post_followed_by_timeout_stays_unverified_without_duplicate(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()
    client.raise_after_add = TimeoutError("response lost")

    failed = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert failed["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1

    client.raise_after_add = None
    recovered = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=15)
    )
    assert recovered["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert recovered["sent"] is False
    assert len(client.add_calls) == 1
    assert len(client.rows[DAY]) == 1


async def test_failure_sets_backoff_and_warn_alert(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(fail_fetch=RuntimeError("Garmin unavailable"))

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    row = await _outbox(db_session)

    assert result["status"] == WEIGHT_EXPORT_FAILED
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(minutes=15)
    assert "Garmin unavailable" in row.last_error
    alerts = await alerts_service.list_active(db_session, domain="garmin")
    assert [a.alert_key for a in alerts] == [garmin_weight_service.ALERT_KEY]

    # A scheduler tick inside the backoff window makes no upstream request.
    client.fail_fetch = None
    await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=14)
    )
    assert len(client.fetch_calls) == 1


async def test_retry_preflight_keeps_previous_alert_until_recovery(db_session):
    await _manual_weight(db_session, 84.5)
    failed_client = FakeWeightClient(fail_fetch=RuntimeError("Garmin unavailable"))
    await garmin_weight_service.export_latest(db_session, failed_client, now=NOW)
    await db_session.commit()
    assert await alerts_service.list_active(db_session, domain="garmin")

    fetch_started = asyncio.Event()
    never_resume = asyncio.Event()

    class PausingClient(FakeWeightClient):
        async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
            self.fetch_calls.append(on_date)
            fetch_started.set()
            await never_resume.wait()
            return {"dateWeightList": []}

    task = asyncio.create_task(
        garmin_weight_service.export_latest(
            db_session,
            PausingClient(),
            now=NOW + timedelta(minutes=15),
            force=True,
        )
    )
    await asyncio.wait_for(fetch_started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    row = await _outbox(db_session)
    assert row.status == WEIGHT_EXPORT_CHECKING
    assert "Garmin unavailable" in row.last_error
    assert await alerts_service.list_active(db_session, domain="garmin")


async def test_export_uses_live_freshness_and_retry_preferences(db_session):
    await prefs.set_prefs(
        db_session,
        {
            "garmin_weight_export_minutes": 20,
            "garmin_weight_max_age_days": 1,
        },
    )
    await _manual_weight(db_session, 84.5, on_date=DAY - timedelta(days=2))
    client = FakeWeightClient(fail_fetch=RuntimeError("must stay local"))

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result == {"status": "empty", "sent": False}
    assert client.fetch_calls == []

    await _manual_weight(db_session, 84.0, on_date=DAY)
    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_FAILED
    assert (await _outbox(db_session)).next_attempt_at == NOW + timedelta(minutes=20)


async def test_latest_garmin_import_is_not_echoed_and_older_manual_is_not_backfilled(
    db_session,
):
    await _manual_weight(db_session, 85.0, on_date=DAY - timedelta(days=1))
    await weight_service.log_weight(
        db_session,
        on_date=DAY,
        weight_kg=84.5,
        source=Source.GARMIN_API.value,
    )
    client = FakeWeightClient()

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result == {"status": "empty", "sent": False}
    assert client.fetch_calls == []
    row = await _outbox(db_session)
    assert row.status == WEIGHT_EXPORT_SKIPPED
    assert row.weight_log_id is not None


async def test_stale_weight_is_not_exported(db_session):
    await _manual_weight(
        db_session,
        85.0,
        on_date=DAY - timedelta(days=31),
    )
    client = FakeWeightClient()

    assert await garmin_weight_service.export_latest(db_session, client, now=NOW) == {
        "status": "empty",
        "sent": False,
    }
    assert client.fetch_calls == []


async def test_disabled_job_never_constructs_a_garmin_client(
    db_session, session_factory, monkeypatch
):
    def explode(*_args, **_kwargs):
        raise AssertionError("disabled export must not create a Garmin client")

    monkeypatch.setattr(GarminClient, "from_config", explode)
    await garmin_weight_service.export_job(session_factory, redis=None)


async def test_unconfigured_job_does_not_reconcile_retry_or_alert(
    session_factory, monkeypatch
):
    class UnconfiguredClient:
        is_configured = False

        async def fetch_daily_weigh_ins(self, _on_date):
            raise AssertionError("an unconfigured job must not touch Garmin")

    async with session_factory() as session:
        await weight_service.log_weight(
            session,
            on_date=DAY,
            weight_kg=84.5,
            source=Source.MANUAL.value,
        )
        await garmin_weight_service.set_enabled(session, True, now=NOW)
        row = await _outbox(session)
        row.attempts = 3
        row.last_error = "unchanged"
        await session.commit()

    monkeypatch.setattr(
        GarminClient, "from_config", lambda *args, **kwargs: UnconfiguredClient()
    )
    await garmin_weight_service.export_job(session_factory, redis=None)

    async with session_factory() as session:
        row = await _outbox(session)
        assert row.status == WEIGHT_EXPORT_PENDING
        assert row.attempts == 3
        assert row.last_error == "unchanged"
        assert await alerts_service.list_active(session, domain="garmin") == []


async def test_weight_job_surfaces_garmin_token_cache_warnings(
    session_factory, monkeypatch
):
    class WarningClient(FakeWeightClient):
        is_configured = True
        token_warnings = ["token store unavailable"]

    async with session_factory() as session:
        await _manual_weight(session, 84.5)
        await garmin_weight_service.set_enabled(session, True, now=NOW)
        await session.commit()

    monkeypatch.setattr(
        GarminClient, "from_config", lambda *args, **kwargs: WarningClient()
    )
    await garmin_weight_service.export_job(session_factory, redis=None)

    async with session_factory() as session:
        alerts = await alerts_service.list_active(session, domain="garmin")
        token_alerts = [
            alert for alert in alerts if alert.alert_key == garmin_service.TOKEN_ALERT_KEY
        ]
        assert len(token_alerts) == 1
        assert "token store unavailable" in token_alerts[0].message


async def test_different_or_multiple_external_records_block_all_mutations(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient([{"samplePk": "external", "weight": 85000}])

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert client.add_calls == []
    assert client.delete_calls == []

    client.rows[DAY].append({"samplePk": "second", "weight": 84500})
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=15), force=True
    )
    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert client.add_calls == []
    assert client.delete_calls == []


async def test_malformed_nonempty_remote_day_fails_closed(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient([None])

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert client.add_calls == []


async def test_unverified_never_claims_one_match_from_a_multi_entry_day(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()
    client.raise_after_add = TimeoutError("response lost")
    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED

    client.raise_after_add = None
    client.rows[DAY] = [
        {"samplePk": "external-match", "weight": 84500},
        {"samplePk": "external-other", "weight": 85000},
    ]
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=15), force=True
    )
    row = await _outbox(db_session)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert row.remote_owned is False

    await weight_service.delete_weight_log(db_session, local.id)
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=16), force=True
    )
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert client.delete_calls == []


async def test_delete_pending_without_verified_ownership_never_deletes_by_weight(
    db_session,
):
    db_session.add(
        GarminWeightExport(
            date=DAY,
            weight_kg=84.5,
            measured_at=NOW,
            status=WEIGHT_EXPORT_DELETE_PENDING,
            remote_weight_kg=84.5,
            remote_owned=False,
        )
    )
    await db_session.flush()
    client = FakeWeightClient([{"samplePk": "external", "weight": 84500}])

    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW, force=True
    )

    assert result["status"] == WEIGHT_EXPORT_DELETE_FAILED
    assert client.delete_calls == []


async def test_owned_record_next_to_foreign_record_blocks_correction(db_session):
    await _manual_weight(db_session, 85.0)
    client = FakeWeightClient()
    await garmin_weight_service.export_latest(db_session, client, now=NOW)
    client.rows[DAY].append({"samplePk": "external", "weight": 86000})
    await _manual_weight(db_session, 84.0)

    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1)
    )

    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert client.delete_calls == []
    assert len(client.add_calls) == 1


async def test_successful_post_with_failed_readback_stays_unverified_without_retry(
    db_session,
):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=False)
    client.fail_readback = RuntimeError("read-back unavailable")

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1

    # Even when the record cannot be found later, an automatic tick never repeats
    # a POST that Garmin already returned success for.
    client.fail_readback = None
    client.rows[DAY] = []
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=15)
    )
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1

    # Even an explicit Send now only performs a fresh safe reconciliation; it
    # cannot weaken the no-duplicate invariant.
    result = await garmin_weight_service.export_latest(
        db_session,
        client,
        now=NOW + timedelta(minutes=16),
        force=True,
    )
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1


async def test_unverified_dispatch_marker_survives_rollback_and_blocks_duplicate(
    db_session,
):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=False)

    first = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert first["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1

    # Simulate process loss after Garmin accepted the request but before the
    # caller's final commit. The pre-dispatch state must already be durable.
    await db_session.rollback()
    assert (await _outbox(db_session)).status == WEIGHT_EXPORT_UNVERIFIED
    client.rows[DAY] = []  # eventual-consistency lag must not reopen POST

    second = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )
    assert second["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert len(client.add_calls) == 1


async def test_equal_record_appearing_after_post_is_never_claimed_as_owned(db_session):
    class InterleavedExternalClient(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            self.add_calls.append((weight_kg, measured_at))
            # Our successful 204 response has no identity and its row is not yet
            # visible; an unrelated client writes the same value in the meantime.
            self.rows[measured_at.date()] = [
                {"samplePk": "external-race", "weight": weight_kg * 1000}
            ]
            return None

    local = await _manual_weight(db_session, 84.5)
    client = InterleavedExternalClient(response_has_sample_pk=False)

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    row = await _outbox(db_session)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert row.remote_owned is False
    assert row.remote_sample_pk is None

    await weight_service.delete_weight_log(db_session, local.id)
    await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )
    assert client.delete_calls == []


async def test_response_sample_pk_establishes_ownership_without_readback(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=True)
    client.fail_readback = RuntimeError("must not be needed")

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result["status"] == WEIGHT_EXPORT_SENT
    row = await _outbox(db_session)
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"
    assert len(client.fetch_calls) == 1


async def test_response_sample_pk_ownership_survives_caller_rollback(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=True)

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_SENT

    # Simulate caller/process loss after the service returned. The response is
    # the sole exact deletion token and therefore has to be internally durable.
    await db_session.rollback()
    row = await _outbox(db_session)
    assert row.status == WEIGHT_EXPORT_SENT
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"


async def test_normal_204_response_claims_exact_timestamped_readback(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result == {"status": WEIGHT_EXPORT_SENT, "sent": True, "date": DAY}
    row = await _outbox(db_session)
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"
    assert len(client.add_calls) == 1
    assert len(client.fetch_calls) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "timestamp_plus_one",
        "timestamp_string",
        "timestamp_float",
        "timestamp_seconds",
        "wrong_source",
        "lowercase_source",
        "missing_source",
        "missing_sample_pk",
        "generic_id_only",
        "missing_timestamp",
        "one_gram_difference",
    ],
)
async def test_204_readback_requires_every_exact_correlation_field(
    db_session, mutation
):
    class MutatedCorrelationClient(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            response = await super().add_weigh_in(weight_kg, measured_at)
            remote = self.rows[measured_at.date()][-1]
            if mutation == "timestamp_plus_one":
                remote["timestampGMT"] += 1
            elif mutation == "timestamp_string":
                remote["timestampGMT"] = str(remote["timestampGMT"])
            elif mutation == "timestamp_float":
                remote["timestampGMT"] = float(remote["timestampGMT"])
            elif mutation == "timestamp_seconds":
                remote["timestampGMT"] //= 1000
            elif mutation == "wrong_source":
                remote["sourceType"] = "FITNESS_DEVICE"
            elif mutation == "lowercase_source":
                remote["sourceType"] = "manual"
            elif mutation == "missing_source":
                remote.pop("sourceType")
            elif mutation == "missing_sample_pk":
                remote.pop("samplePk")
            elif mutation == "generic_id_only":
                remote["id"] = remote.pop("samplePk")
            elif mutation == "missing_timestamp":
                remote.pop("timestampGMT")
            elif mutation == "one_gram_difference":
                remote["weight"] += 1
            return response

    await _manual_weight(db_session, 84.5)
    client = MutatedCorrelationClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    row = await _outbox(db_session)
    assert row.remote_owned is False
    assert row.remote_sample_pk is None
    assert len(client.add_calls) == 1


async def test_legacy_zero_millisecond_timestamp_can_never_establish_ownership(
    db_session,
):
    await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    row = await _outbox(db_session)
    row.status = WEIGHT_EXPORT_UNVERIFIED
    row.measured_at = NOW
    row.remote_weight_kg = 84.5
    row.remote_sample_pk = None
    row.remote_owned = False
    await db_session.flush()
    client = FakeWeightClient(
        [
            {
                "samplePk": "legacy-looking",
                "weight": 84_500,
                "sourceType": "MANUAL",
                "timestampGMT": garmin_weight_service._dispatch_timestamp_ms(NOW),
            }
        ]
    )

    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW, force=True
    )

    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    row = await _outbox(db_session)
    assert row.remote_owned is False
    assert row.remote_sample_pk is None
    assert client.add_calls == []


async def test_204_exact_entry_next_to_foreign_entry_is_never_claimed(db_session):
    class ExtraEntryClient(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            response = await super().add_weigh_in(weight_kg, measured_at)
            self.rows[measured_at.date()].append(
                {"samplePk": "foreign", "weight": 83_000, "sourceType": "MANUAL"}
            )
            return response

    await _manual_weight(db_session, 84.5)
    client = ExtraEntryClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    row = await _outbox(db_session)
    assert row.remote_owned is False
    assert row.remote_sample_pk is None


async def test_timed_out_post_later_claims_its_exact_timestamped_record(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )
    client.raise_after_add = TimeoutError("response lost")

    first = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert first["status"] == WEIGHT_EXPORT_UNVERIFIED

    client.raise_after_add = None
    second = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert second["status"] == WEIGHT_EXPORT_SENT
    row = await _outbox(db_session)
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"
    assert len(client.add_calls) == 1


async def test_late_exact_claim_survives_timezone_change(db_session, monkeypatch):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )
    client.raise_after_add = TimeoutError("response lost")
    first = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert first["status"] == WEIGHT_EXPORT_UNVERIFIED
    persisted_epoch = (await _outbox(db_session)).dispatch_timestamp_ms
    assert persisted_epoch is not None

    monkeypatch.setattr(
        garmin_weight_service,
        "load_config",
        lambda: Config(
            database_url="sqlite+aiosqlite://",
            redis_url="redis://unused",
            timezone="Pacific/Honolulu",
        ),
    )
    client.raise_after_add = None
    recovered = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert recovered["status"] == WEIGHT_EXPORT_SENT
    row = await _outbox(db_session)
    assert row.dispatch_timestamp_ms == persisted_epoch
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"


async def test_204_exact_ownership_survives_caller_rollback(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )

    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_SENT

    await db_session.rollback()
    row = await _outbox(db_session)
    assert row.status == WEIGHT_EXPORT_SENT
    assert row.remote_owned is True
    assert row.remote_sample_pk == "100"


async def test_delete_owned_latest_removes_remote_and_never_backfills_older_weight(
    db_session,
):
    await _manual_weight(db_session, 85.0, on_date=DAY - timedelta(days=1))
    latest = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert await weight_service.delete_weight_log(db_session, latest.id) is True
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert result["status"] == WEIGHT_EXPORT_DELETED
    assert client.delete_calls == [("100", DAY)]
    assert len(client.add_calls) == 1
    assert client.rows[DAY] == []
    assert (
        await db_session.execute(
            select(GarminWeightExport).where(
                GarminWeightExport.date == DAY - timedelta(days=1)
            )
        )
    ).scalar_one_or_none() is None


async def test_delete_external_match_never_deletes_the_garmin_record(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient([{"samplePk": "external", "weight": 84500}])
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert await weight_service.delete_weight_log(db_session, local.id) is True
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert result["status"] == "empty"
    assert client.delete_calls == []
    assert client.rows[DAY] == [{"samplePk": "external", "weight": 84500}]
    assert (await _outbox(db_session)).status == WEIGHT_EXPORT_DELETED


async def test_delete_failure_keeps_cleanup_intent_and_recovers_without_post(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, client, now=NOW)
    await weight_service.delete_weight_log(db_session, local.id)
    client.fail_delete = TimeoutError("delete outcome unknown")

    failed = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )
    assert failed["status"] == WEIGHT_EXPORT_DELETE_FAILED
    assert len(client.add_calls) == 1

    client.fail_delete = None
    recovered = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=2), force=True
    )
    assert recovered["status"] == WEIGHT_EXPORT_DELETED
    assert len(client.add_calls) == 1
    assert client.rows[DAY] == []


async def test_deleting_unverified_post_never_claims_or_deletes_readback_record(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=False)
    client.fail_readback = RuntimeError("read-back unavailable")
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED

    await weight_service.delete_weight_log(db_session, local.id)
    client.fail_readback = None
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert client.delete_calls == []
    assert len(client.rows[DAY]) == 1


async def test_deleted_unverified_post_stays_unresolved_until_remote_appears(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient(response_has_sample_pk=False)
    client.fail_readback = RuntimeError("read-back unavailable")
    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    await weight_service.delete_weight_log(db_session, local.id)
    assert "deleted" in (await _outbox(db_session)).last_error.lower()

    client.fail_readback = None
    client.rows[DAY] = []
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=15), force=True
    )
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert client.delete_calls == []

    client.rows[DAY] = [{"samplePk": "late", "weight": 84500}]
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=16), force=True
    )
    assert result["status"] == WEIGHT_EXPORT_UNVERIFIED
    assert client.delete_calls == []


async def test_delete_same_day_correction_restores_prior_local_value(db_session):
    prior = await _manual_weight(db_session, 85.0)
    latest = await _manual_weight(db_session, 84.0)
    client = FakeWeightClient()
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, client, now=NOW)

    assert await weight_service.delete_weight_log(db_session, latest.id) is True
    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert prior.superseded is False
    assert result["status"] == WEIGHT_EXPORT_SENT
    assert client.delete_calls == [("100", DAY)]
    assert [item["weight"] for item in client.rows[DAY]] == [85000.0]


async def test_owned_small_local_correction_is_not_hidden_by_remote_tolerance(db_session):
    await _manual_weight(db_session, 84.50)
    client = FakeWeightClient()
    await garmin_weight_service.export_latest(db_session, client, now=NOW)
    await _manual_weight(db_session, 84.54)

    result = await garmin_weight_service.export_latest(
        db_session, client, now=NOW + timedelta(minutes=1), force=True
    )

    assert result["status"] == WEIGHT_EXPORT_SENT
    assert len(client.add_calls) == 2
    assert client.add_calls[0][1] != client.add_calls[1][1]
    assert all(call[1].microsecond != 0 for call in client.add_calls)
    assert client.delete_calls == [("100", DAY)]
    assert [item["weight"] for item in client.rows[DAY]] == [84540.0]


async def test_deleting_future_weight_does_not_poison_the_no_backfill_watermark(
    db_session, monkeypatch
):
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: NOW)
    await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    future = await _manual_weight(
        db_session, 83.0, on_date=DAY + timedelta(days=365)
    )

    assert await weight_service.delete_weight_log(db_session, future.id) is True
    current = await garmin_weight_service.reconcile_latest(db_session, now=NOW)

    assert current is not None
    assert current.date == DAY
    rows = (await db_session.execute(select(GarminWeightExport))).scalars().all()
    assert [row.date for row in rows] == [DAY]


@pytest.mark.integration
async def test_newer_weight_save_during_preflight_cancels_older_post(
    db_session, monkeypatch,
):
    """PostgreSQL regression: DB locks cover transitions, never Garmin latency."""
    race_now = NOW + timedelta(days=1)
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: race_now)
    await _manual_weight(db_session, 85.0)
    await garmin_weight_service.set_enabled(db_session, True, now=race_now)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    preflight_started = asyncio.Event()
    resume_preflight = asyncio.Event()

    class PausingClient(FakeWeightClient):
        async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
            self.fetch_calls.append(on_date)
            preflight_started.set()
            await resume_preflight.wait()
            return {"dateWeightList": []}

    client = PausingClient()

    async def export_older():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=race_now, require_enabled=True
            )
            await session.commit()
            return result

    older_task = asyncio.create_task(export_older())
    await asyncio.wait_for(preflight_started.wait(), timeout=2)

    async with factory() as session:
        await _manual_weight(session, 84.0, on_date=race_now.date())
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_preflight.set()
    result = await asyncio.wait_for(older_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_SKIPPED
    assert client.add_calls == []


@pytest.mark.integration
async def test_local_delete_is_not_blocked_by_garmin_preflight_and_cancels_post(
    db_session,
):
    local = await _manual_weight(db_session, 84.5)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    preflight_started = asyncio.Event()
    resume_preflight = asyncio.Event()

    class PausingClient(FakeWeightClient):
        async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
            self.fetch_calls.append(on_date)
            preflight_started.set()
            await resume_preflight.wait()
            return {"dateWeightList": []}

    client = PausingClient()

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(session, client, now=NOW)
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(preflight_started.wait(), timeout=2)

    async with factory() as session:
        assert await weight_service.delete_weight_log(session, local.id) is True
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_preflight.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_DELETED
    assert client.add_calls == []


@pytest.mark.integration
async def test_correction_during_nonempty_preflight_cannot_finalize_stale_match(
    db_session, monkeypatch,
):
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: NOW)
    await _manual_weight(db_session, 85.0)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    preflight_started = asyncio.Event()
    resume_preflight = asyncio.Event()

    class PausingEqualClient(FakeWeightClient):
        async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
            self.fetch_calls.append(on_date)
            preflight_started.set()
            await resume_preflight.wait()
            return {
                "dateWeightList": [{"samplePk": "external", "weight": 85000}]
            }

    client = PausingEqualClient()

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=NOW, require_enabled=True
            )
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(preflight_started.wait(), timeout=2)

    async with factory() as session:
        await _manual_weight(session, 84.0)
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_preflight.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_PENDING
    async with factory() as session:
        row = await _outbox(session)
        assert row.status == WEIGHT_EXPORT_PENDING
        assert row.weight_kg == 84.0
        assert row.remote_owned is False


@pytest.mark.integration
async def test_opt_out_during_preflight_cancels_post(db_session):
    await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    preflight_started = asyncio.Event()
    resume_preflight = asyncio.Event()

    class PausingEmptyClient(FakeWeightClient):
        async def fetch_daily_weigh_ins(self, on_date: date) -> dict:
            self.fetch_calls.append(on_date)
            preflight_started.set()
            await resume_preflight.wait()
            return {"dateWeightList": []}

    client = PausingEmptyClient()

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=NOW, require_enabled=True
            )
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(preflight_started.wait(), timeout=2)

    async with factory() as session:
        await garmin_weight_service.set_enabled(session, False, now=NOW)
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_preflight.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_SKIPPED
    assert client.add_calls == []


@pytest.mark.integration
@pytest.mark.parametrize("response_has_sample_pk", [True, False])
async def test_exact_post_identity_survives_concurrent_local_delete(
    db_session, response_has_sample_pk
):
    local = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    post_started = asyncio.Event()
    resume_response = asyncio.Event()

    class PausingResponseClient(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            response = await super().add_weigh_in(weight_kg, measured_at)
            post_started.set()
            await resume_response.wait()
            return response

    client = PausingResponseClient(
        response_has_sample_pk=response_has_sample_pk,
        include_correlation_fields=not response_has_sample_pk,
    )

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=NOW, require_enabled=True
            )
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(post_started.wait(), timeout=2)

    async with factory() as session:
        assert await weight_service.delete_weight_log(session, local.id) is True
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_response.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_DELETE_PENDING
    async with factory() as session:
        row = await _outbox(session)
        assert row.status == WEIGHT_EXPORT_DELETE_PENDING
        assert row.weight_log_id is None
        assert row.remote_owned is True
        assert row.remote_sample_pk == "100"


@pytest.mark.integration
@pytest.mark.parametrize("response_has_sample_pk", [True, False])
async def test_exact_post_identity_preserves_concurrent_correction(
    db_session, monkeypatch, response_has_sample_pk
):
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: NOW)
    await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    post_started = asyncio.Event()
    resume_response = asyncio.Event()

    class PausingResponseClient(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            response = await super().add_weigh_in(weight_kg, measured_at)
            post_started.set()
            await resume_response.wait()
            return response

    client = PausingResponseClient(
        response_has_sample_pk=response_has_sample_pk,
        include_correlation_fields=not response_has_sample_pk,
    )

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=NOW, require_enabled=True
            )
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(post_started.wait(), timeout=2)

    async with factory() as session:
        await _manual_weight(session, 84.0)
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_response.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_PENDING
    async with factory() as session:
        row = await _outbox(session)
        assert row.status == WEIGHT_EXPORT_PENDING
        assert row.weight_kg == 84.0
        assert row.remote_weight_kg == 84.5
        assert row.remote_owned is True
        assert row.remote_sample_pk == "100"


@pytest.mark.integration
async def test_204_exact_readback_survives_concurrent_opt_out(db_session):
    await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    post_started = asyncio.Event()
    resume_response = asyncio.Event()

    class Pausing204Client(FakeWeightClient):
        async def add_weigh_in(self, weight_kg: float, measured_at: datetime):
            response = await super().add_weigh_in(weight_kg, measured_at)
            post_started.set()
            await resume_response.wait()
            return response

    client = Pausing204Client(
        response_has_sample_pk=False,
        include_correlation_fields=True,
    )

    async def exporting():
        async with factory() as session:
            result = await garmin_weight_service.export_latest(
                session, client, now=NOW, require_enabled=True
            )
            await session.commit()
            return result

    export_task = asyncio.create_task(exporting())
    await asyncio.wait_for(post_started.wait(), timeout=2)

    async with factory() as session:
        await garmin_weight_service.set_enabled(session, False, now=NOW)
        await asyncio.wait_for(session.commit(), timeout=2)

    resume_response.set()
    result = await asyncio.wait_for(export_task, timeout=2)

    assert result["status"] == WEIGHT_EXPORT_SENT
    async with factory() as session:
        row = await _outbox(session)
        assert await garmin_weight_service.is_enabled(session) is False
        assert row.status == WEIGHT_EXPORT_SENT
        assert row.remote_owned is True
        assert row.remote_sample_pk == "100"


@pytest.mark.integration
async def test_active_delete_takes_advisory_before_outbox_fk_lock(
    db_session, monkeypatch
):
    """Regression for advisory→outbox lock ordering (the reverse deadlocks)."""
    local = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    delete_reached_lock = asyncio.Event()
    original_lock = garmin_weight_service.lock_active_weight_change

    async def signaling_lock(session):
        delete_reached_lock.set()
        await original_lock(session)

    monkeypatch.setattr(
        garmin_weight_service, "lock_active_weight_change", signaling_lock
    )

    async with factory() as exporter_session:
        await garmin_weight_service._acquire_operation_lock(exporter_session)

        async def deleting():
            async with factory() as session:
                deleted = await weight_service.delete_weight_log(session, local.id)
                await session.commit()
                return deleted

        delete_task = asyncio.create_task(deleting())
        await asyncio.wait_for(delete_reached_lock.wait(), timeout=2)

        row = await _outbox(exporter_session)
        row.last_error = "lock-order probe"
        await exporter_session.flush()
        await exporter_session.commit()

    assert await asyncio.wait_for(delete_task, timeout=2) is True


@pytest.mark.integration
async def test_stale_inactive_delete_reloads_row_after_advisory_lock(db_session):
    """A concurrent delete may reactivate an object cached as superseded."""
    prior = await _manual_weight(db_session, 85.0)
    current = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, FakeWeightClient(), now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async with factory() as stale_session:
        cached_prior = (
            await stale_session.execute(
                select(WeightLog).where(WeightLog.id == prior.id)
            )
        ).scalar_one()
        assert cached_prior.superseded is True

        async with factory() as other_session:
            assert await weight_service.delete_weight_log(
                other_session, current.id
            ) is True
            await other_session.commit()

        # This Python object is deliberately stale. delete_weight_log must take
        # the advisory first and repopulate it before deciding whether cleanup is
        # required.
        assert cached_prior.superseded is True
        assert await weight_service.delete_weight_log(
            stale_session, prior.id
        ) is True
        await stale_session.commit()

    async with factory() as check_session:
        assert (
            await check_session.execute(select(func.count()).select_from(WeightLog))
        ).scalar_one() == 0
        row = await _outbox(check_session)
        assert row.status == WEIGHT_EXPORT_DELETE_PENDING
        assert row.weight_log_id is None
        assert row.remote_owned is True
        assert row.remote_sample_pk == "100"


@pytest.mark.integration
async def test_stale_inactive_cache_does_not_break_concurrent_weight_save(
    db_session, monkeypatch
):
    # The save hook reconciles against the wall clock; pin it to the fixture day
    # or the weight ages past the export window and the outbox turns 'skipped'.
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: NOW)
    prior = await _manual_weight(db_session, 85.0)
    current = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, FakeWeightClient(), now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async with factory() as stale_session:
        cached_prior = (
            await stale_session.execute(
                select(WeightLog).where(WeightLog.id == prior.id)
            )
        ).scalar_one()
        assert cached_prior.superseded is True

        async with factory() as other_session:
            assert await weight_service.delete_weight_log(
                other_session, current.id
            ) is True
            await other_session.commit()

        saved = await _manual_weight(stale_session, 83.0)
        await stale_session.commit()

    async with factory() as check_session:
        rows = (
            await check_session.execute(
                select(WeightLog).order_by(WeightLog.id)
            )
        ).scalars().all()
        assert [(row.id, row.weight_kg, row.superseded) for row in rows] == [
            (prior.id, 85.0, True),
            (saved.id, 83.0, False),
        ]
        outbox = await _outbox(check_session)
        assert outbox.status == WEIGHT_EXPORT_PENDING
        assert outbox.weight_log_id == saved.id
        assert outbox.weight_kg == 83.0


@pytest.mark.integration
async def test_stale_inactive_cache_is_refreshed_before_same_date_edit(
    db_session, monkeypatch
):
    monkeypatch.setattr(garmin_weight_service, "now_local", lambda: NOW)
    prior = await _manual_weight(db_session, 85.0)
    current = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async with factory() as stale_session:
        cached_prior = (
            await stale_session.execute(
                select(WeightLog).where(WeightLog.id == prior.id)
            )
        ).scalar_one()
        assert cached_prior.superseded is True

        async with factory() as other_session:
            assert await weight_service.delete_weight_log(
                other_session, current.id
            ) is True
            await other_session.commit()

        edited = await weight_service.update_weight_log(
            stale_session,
            prior.id,
            on_date=DAY,
            weight_kg=83.0,
        )
        assert edited is not None
        await stale_session.commit()

    async with factory() as check_session:
        active = await weight_service.get_active_weight(check_session, DAY)
        assert active is not None
        assert active.id == prior.id
        assert active.weight_kg == 83.0
        outbox = await _outbox(check_session)
        assert outbox.status == WEIGHT_EXPORT_PENDING
        assert outbox.weight_log_id == prior.id
        assert outbox.weight_kg == 83.0


@pytest.mark.integration
async def test_delete_hook_refreshes_newest_owned_sample_pk(db_session):
    local = await _manual_weight(db_session, 84.5)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.export_latest(db_session, FakeWeightClient(), now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async with factory() as stale_session:
        cached_outbox = await _outbox(stale_session)
        assert cached_outbox.remote_sample_pk == "100"

        async with factory() as finalizer_session:
            await garmin_weight_service._acquire_operation_lock(finalizer_session)
            fresh = await _outbox(finalizer_session)
            fresh.remote_sample_pk = "101"
            fresh.remote_owned = True
            await finalizer_session.commit()

        assert await weight_service.delete_weight_log(
            stale_session, local.id
        ) is True
        await stale_session.commit()

    async with factory() as check_session:
        outbox = await _outbox(check_session)
        assert outbox.status == WEIGHT_EXPORT_DELETE_PENDING
        assert outbox.remote_owned is True
        assert outbox.remote_sample_pk == "101"


@pytest.mark.integration
async def test_reconcile_refreshes_cached_weight_after_concurrent_edit(db_session):
    local = await _manual_weight(db_session, 85.0)
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await db_session.commit()
    factory = async_sessionmaker(
        db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    async with factory() as stale_session:
        cached = (
            await stale_session.execute(
                select(WeightLog).where(WeightLog.id == local.id)
            )
        ).scalar_one()
        assert cached.weight_kg == 85.0

        async with factory() as other_session:
            edited = await weight_service.update_weight_log(
                other_session,
                local.id,
                on_date=DAY,
                weight_kg=84.0,
            )
            assert edited is not None
            await other_session.commit()

        await garmin_weight_service.reconcile_latest(stale_session, now=NOW)
        await stale_session.commit()

    async with factory() as check_session:
        outbox = await _outbox(check_session)
        assert outbox.status == WEIGHT_EXPORT_PENDING
        assert outbox.weight_kg == 84.0


async def test_cursor_survives_disable_and_blocks_exposed_older_manual_weight(db_session):
    await _manual_weight(db_session, 85.0, on_date=DAY - timedelta(days=1))
    newest = await weight_service.log_weight(
        db_session,
        on_date=DAY,
        weight_kg=84.5,
        source=Source.GARMIN_API.value,
    )
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)
    await garmin_weight_service.set_enabled(db_session, False, now=NOW)

    assert await weight_service.delete_weight_log(db_session, newest.id) is True
    await garmin_weight_service.set_enabled(db_session, True, now=NOW)

    rows = (await db_session.execute(select(GarminWeightExport))).scalars().all()
    assert [(row.date, row.status) for row in rows] == [(DAY, WEIGHT_EXPORT_DELETED)]


async def test_watermark_bootstraps_from_newer_historical_outbox(db_session):
    await _manual_weight(db_session, 85.0, on_date=DAY - timedelta(days=1))
    db_session.add(
        GarminWeightExport(
            date=DAY,
            weight_kg=84.5,
            measured_at=NOW,
            status=WEIGHT_EXPORT_DELETED,
        )
    )
    await db_session.flush()

    result = await garmin_weight_service.reconcile_latest(db_session, now=NOW)

    assert result is None
    rows = (await db_session.execute(select(GarminWeightExport))).scalars().all()
    assert [(row.date, row.status) for row in rows] == [(DAY, WEIGHT_EXPORT_DELETED)]


async def test_reactivating_skipped_intent_resets_the_entire_retry_state(db_session):
    await _manual_weight(db_session, 84.5)
    row = await garmin_weight_service.reconcile_latest(db_session, now=NOW)
    assert row is not None
    row.status = WEIGHT_EXPORT_SKIPPED
    row.attempts = 5
    row.last_attempt_at = NOW
    row.next_attempt_at = NOW + timedelta(hours=6)
    row.last_error = "old failure"
    await db_session.flush()

    row = await garmin_weight_service.reconcile_latest(db_session, now=NOW)

    assert row.status == WEIGHT_EXPORT_PENDING
    assert row.attempts == 0
    assert row.last_attempt_at is None
    assert row.next_attempt_at is None
    assert row.last_error is None


async def test_status_card_prioritizes_unresolved_cleanup_over_newer_success(db_session):
    await _manual_weight(db_session, 84.5)
    client = FakeWeightClient()
    await garmin_weight_service.export_latest(db_session, client, now=NOW)
    db_session.add(
        GarminWeightExport(
            date=DAY - timedelta(days=1),
            weight_kg=85.0,
            measured_at=NOW - timedelta(days=1),
            status=WEIGHT_EXPORT_DELETE_FAILED,
            last_error="cleanup failed",
        )
    )
    await db_session.flush()

    status = await garmin_weight_service.get_status(db_session)

    assert status["status"] == WEIGHT_EXPORT_DELETE_FAILED
    assert status["date"] == DAY - timedelta(days=1)
    assert status["last_error"] == "cleanup failed"


async def test_alert_keeps_the_highest_priority_outstanding_issue(db_session):
    older = DAY - timedelta(days=1)
    db_session.add(
        GarminWeightExport(
            date=older,
            weight_kg=85.0,
            measured_at=NOW - timedelta(days=1),
            status=WEIGHT_EXPORT_DELETE_FAILED,
            next_attempt_at=NOW + timedelta(hours=1),
            last_error="owned cleanup failed",
        )
    )
    await db_session.flush()
    await garmin_weight_service._resolve_alert_if_clear(db_session)
    await _manual_weight(db_session, 84.5)

    result = await garmin_weight_service.export_latest(
        db_session,
        FakeWeightClient(fail_fetch=RuntimeError("new send failed")),
        now=NOW,
    )

    assert result["status"] == WEIGHT_EXPORT_FAILED
    alerts = await alerts_service.list_active(db_session, domain="garmin")
    assert len(alerts) == 1
    assert older.isoformat() in alerts[0].message
    assert "owned cleanup failed" in alerts[0].message
    assert "new send failed" not in alerts[0].message


async def test_deleting_a_conflicted_local_weight_resolves_its_alert(db_session):
    local = await _manual_weight(db_session, 84.5)
    client = FakeWeightClient([{"samplePk": "external", "weight": 85000}])
    result = await garmin_weight_service.export_latest(db_session, client, now=NOW)
    assert result["status"] == WEIGHT_EXPORT_CONFLICT
    assert await alerts_service.list_active(db_session, domain="garmin")

    assert await weight_service.delete_weight_log(db_session, local.id) is True

    assert await alerts_service.list_active(db_session, domain="garmin") == []
    assert (await _outbox(db_session)).status == WEIGHT_EXPORT_DELETED


def test_daily_weigh_in_parser_uses_individual_grams_not_average():
    rows = garmin_weight_service.parse_daily_weigh_ins(
        {
            "dateWeightList": [
                {"samplePk": 1, "weight": 84500},
                {"samplePk": 2, "weight": 84.0},
            ],
            "totalAverage": {"weight": 99999},
        }
    )
    assert [(row.sample_pk, row.weight_kg) for row in rows] == [
        ("1", 84.5),
        ("2", 84.0),
    ]


@pytest.mark.parametrize("payload", [None, {"dateWeightList": [None]}])
def test_daily_weigh_in_parser_rejects_ambiguous_empty_or_malformed_payload(payload):
    with pytest.raises(ValueError):
        garmin_weight_service.parse_daily_weigh_ins(payload)


def test_daily_weigh_in_parser_accepts_explicit_empty_payloads():
    assert garmin_weight_service.parse_daily_weigh_ins({}) == []
    assert garmin_weight_service.parse_daily_weigh_ins([]) == []


class _RawWeightGarmin:
    def __init__(self):
        self.calls = []

    def get_daily_weigh_ins(self, day):
        self.calls.append(("get", day))
        return {"dateWeightList": []}

    def add_weigh_in(self, weight, *, unitKey, timestamp):
        self.calls.append(("add", weight, unitKey, timestamp))
        return {"samplePk": 9}

    def delete_weigh_in(self, sample_pk, day):
        self.calls.append(("delete", sample_pk, day))


async def test_garmin_client_weight_methods_preserve_local_date_and_contract():
    raw = _RawWeightGarmin()
    client = GarminClient(
        Config(database_url="", redis_url="", timezone="Asia/Almaty")
    )
    client._garmin = raw

    assert await client.fetch_daily_weigh_ins(DAY) == {"dateWeightList": []}
    assert await client.add_weigh_in(84.5, datetime(2026, 8, 15, 23, 45)) == {
        "samplePk": 9
    }
    await client.delete_weigh_in("9", DAY)

    assert raw.calls == [
        ("get", "2026-08-15"),
        ("add", 84.5, "kg", "2026-08-15T23:45:00.000+05:00"),
        ("delete", "9", "2026-08-15"),
    ]


def test_0034_quarantines_every_ambiguous_legacy_export(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.0034_garmin_weight_export_safety_upgrade"
    )
    metadata = sa.MetaData()
    exports = sa.Table(
        "garmin_weight_exports",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("weight_kg", sa.Float, nullable=False),
        sa.Column("measured_at", sa.DateTime, nullable=False),
        sa.Column("remote_sample_pk", sa.String(64)),
        sa.Column("remote_weight_kg", sa.Float),
        sa.Column("remote_owned", sa.Boolean, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime),
        sa.Column("last_error", sa.Text),
        sa.Column("updated_at", sa.DateTime),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            exports.insert(),
            [
                {
                    "id": 1,
                    "status": "pending",
                    "weight_kg": 84.5,
                    "measured_at": NOW.replace(microsecond=123456),
                    "remote_sample_pk": None,
                    "remote_owned": False,
                },
                {
                    "id": 2,
                    "status": "failed",
                    "weight_kg": 84.0,
                    "measured_at": NOW.replace(microsecond=654321),
                    "remote_sample_pk": None,
                    "remote_owned": False,
                },
                {
                    "id": 3,
                    "status": "sent",
                    "weight_kg": 83.5,
                    "measured_at": NOW,
                    "remote_sample_pk": "inferred",
                    "remote_owned": True,
                },
                {
                    "id": 4,
                    "status": "sent",
                    "weight_kg": 83.0,
                    "measured_at": NOW.replace(microsecond=999000),
                    "remote_sample_pk": None,
                    "remote_owned": False,
                },
                {
                    "id": 5,
                    "status": "skipped",
                    "weight_kg": 82.5,
                    "measured_at": NOW.replace(microsecond=111000),
                    "remote_sample_pk": None,
                    "remote_owned": True,
                },
            ],
        )
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()
        rows = {
            row.id: row
            for row in connection.execute(select(exports).order_by(exports.c.id))
        }
        column_names = {
            column["name"]
            for column in sa.inspect(connection).get_columns(
                "garmin_weight_exports"
            )
        }

    assert rows[1].status == WEIGHT_EXPORT_UNVERIFIED
    assert rows[1].remote_weight_kg == 84.5
    assert rows[1].remote_sample_pk is None
    assert rows[1].measured_at.microsecond == 0
    assert rows[2].status == WEIGHT_EXPORT_UNVERIFIED
    assert rows[2].measured_at.microsecond == 0
    assert rows[3].status == WEIGHT_EXPORT_MATCHED
    assert rows[3].remote_sample_pk == "inferred"
    assert rows[3].remote_owned is False
    assert rows[4].status == WEIGHT_EXPORT_UNVERIFIED
    assert rows[4].measured_at.microsecond == 0
    assert rows[5].status == WEIGHT_EXPORT_SKIPPED
    assert rows[5].measured_at.microsecond == 111000
    assert rows[5].remote_owned is False
    assert "dispatch_timestamp_ms" in column_names
