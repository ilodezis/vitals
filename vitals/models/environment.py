"""Environment — the bedroom's air, measured by a sensor station on the LAN.

Two tables, both ``domain='environment'`` via ``InsightsMixin``:

  * ``environment_samples`` — one row per snapshot the station produced (every 10 s,
    around the clock). Wide rather than tall: the station reports a fixed handful of
    quantities in one atomic snapshot, so a column each reads best on a chart and in
    SQL. Anything the station sends that has no column yet lands in ``extra`` — a
    new sensor is a firmware change, not a migration.
  * ``environment_hourly`` — one row per station-hour, filled by the rollup job from
    the samples. It exists so a week-long chart reads 168 rows instead of 60 000.

Instants are stored as ``timestamptz`` in UTC (``ts``); ``date`` is the *local*
calendar date of that instant (``VITALS_TIMEZONE``), the shared ``(domain, date)``
axis every other domain uses. SQLite (the fast-test path) hands ``timestamptz``
back naive, so every read goes through ``timeutils.as_utc``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.ENVIRONMENT.value

# JSONB on Postgres, generic JSON on the SQLite fast-test path.
_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")

# ``environment_samples.time_basis`` — where ``ts`` came from.
TIME_DEVICE = "device"      # the station's own clock (SNTP-synced)
TIME_RECEIVED = "received"  # the station had no clock yet; Vitals' receipt time

# ``environment_samples.quality`` — a bit mask. 0 = a clean reading.
Q_MISSING = 1        # a sensor had no value yet (null in the snapshot)
Q_OUT_OF_RANGE = 2   # a value was physically impossible; the column is NULL, the
                     # original stays in ``extra``
Q_STALE = 4          # the value did not change for a long time while the counter
                     # kept running (a frozen sensor)
Q_CLOCK_UNSYNCED = 8  # ``ts`` is the receipt time, not the measurement time

# Plausible-range guard (``environment_samples`` columns are NULLed outside it).
CO2_RANGE = (0, 10000)
HUMIDITY_RANGE = (0.0, 100.0)
TEMPERATURE_RANGE = (-20.0, 60.0)


class EnvironmentSample(Base, InsightsMixin, TimestampMixin):
    """One station snapshot. ``(station_id, boot_id, seq)`` identifies it, so a
    snapshot polled twice is still one row."""

    __tablename__ = "environment_samples"
    __table_args__ = (
        insights_index(__tablename__),
        UniqueConstraint(
            "station_id", "boot_id", "seq", name="uq_environment_samples_snapshot"
        ),
        # The read path of every chart: one station over a time range.
        Index("ix_environment_samples_station_ts", "station_id", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[str] = mapped_column(String(16), nullable=False)
    # The station picks a random ``boot`` at every start and counts ``seq`` up from
    # 1, so after a reboot the pair never collides with an older snapshot.
    boot_id: Mapped[str] = mapped_column(String(16), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    time_basis: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TIME_DEVICE, server_default=TIME_DEVICE
    )

    co2_ppm: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Room left for a light sensor; empty until one is fitted.
    lux_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lux_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    quality: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    # rssi, heap, up, fw, chip_t, any new field the station starts sending, and the
    # original value of anything NULLed for being out of range.
    extra: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)


class EnvironmentHourly(Base, InsightsMixin, TimestampMixin):
    """One station-hour of samples, rolled up. ``hour_start`` is the top of the
    hour in UTC; ``date`` is that instant's local calendar date."""

    __tablename__ = "environment_hourly"
    __table_args__ = (
        insights_index(__tablename__),
        UniqueConstraint(
            "station_id", "hour_start", name="uq_environment_hourly_station_hour"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[str] = mapped_column(String(16), nullable=False)
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Share of the hour the station actually reported (by real intervals between
    # snapshots, each capped — see ``rollup``), 0-100.
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    co2_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    co2_min: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    co2_max: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    co2_p90: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    temp_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temp_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    rh_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rh_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rh_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    lux_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lux_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
