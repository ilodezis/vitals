"""Module 6 — Garmin activity & recovery.

The three metric tables carry ``domain='garmin'`` via ``InsightsMixin``:

  * ``garmin_daily`` — one wide row per calendar date holding the day's recovery
    and activity metrics (sleep, HRV, RHR, stress, Body Battery, steps, calories,
    HR, intensity minutes, training readiness, …). Every column is nullable — a
    given day may only have some metrics — and the full upstream JSON lives in
    ``raw_payloads`` so nothing is lost (maximal-parsing principle). One row per
    date regardless of source (``garmin_api`` or the ``health_auto_export`` backup
    channel), upserted by date.
  * ``garmin_activities`` — recorded sport sessions, keyed by Garmin's activity id
    (the upsert key), for correlation with Hevy workouts.
  * ``garmin_intraday`` — the within-day curves behind those day-level scalars:
    stress and Body Battery every ~3 minutes, plus the night's heart rate, SpO2,
    respiration, stress, Body Battery, HRV and movement. One row per sample, tall
    and generic rather than a column per series, so a new series is a new
    ``series_type`` value and never a migration.

``garmin_weight_exports`` is deliberately separate from the metric lake.  It is
an outbox: one row per local calendar date records the desired weight and the
remote Garmin record (if this app created one), making outbound writes
retryable and corrections safe.
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.enums import Domain
from vitals.models.base import Base, TimestampMixin
from vitals.models.mixins import InsightsMixin, insights_index

DOMAIN = Domain.GARMIN.value

# JSONB on Postgres, generic JSON on the SQLite fast-test path (mirrors
# ``raw_payloads``). Used for the variable-shape per-activity detail arrays and
# the night's interval series.
_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")

# ``garmin_intraday.series_type`` values. Stress and Body Battery both come out of
# the one ``get_stress_data`` payload the daily sync downloads; heart rate is its
# own ``get_heart_rates`` call in the same bundle (~2-minute cadence).
SERIES_STRESS = "stress"
SERIES_BODY_BATTERY = "body_battery"
SERIES_HEART_RATE = "heart_rate"

# The night's series — all seven ride in the one ``get_sleep_data``
# payload the daily sync already downloads. Deliberately distinct from the
# whole-day ``stress`` / ``body_battery`` curves above even where they overlap in
# time: these come from a different endpoint at a different cadence, and a night
# is the unit the sleep page reads.
SERIES_SLEEP_HR = "sleep_hr"
SERIES_SLEEP_SPO2 = "sleep_spo2"
SERIES_SLEEP_RESPIRATION = "sleep_respiration"
SERIES_SLEEP_STRESS = "sleep_stress"
SERIES_SLEEP_BB = "sleep_bb"
SERIES_SLEEP_HRV = "sleep_hrv"
SERIES_SLEEP_MOVEMENT = "sleep_movement"

#: The nightly series as one unit — what the sleep page reads and what the day
#: chart excludes.
SLEEP_SERIES_TYPES = (
    SERIES_SLEEP_HR,
    SERIES_SLEEP_SPO2,
    SERIES_SLEEP_RESPIRATION,
    SERIES_SLEEP_STRESS,
    SERIES_SLEEP_BB,
    SERIES_SLEEP_HRV,
    SERIES_SLEEP_MOVEMENT,
)

WEIGHT_EXPORT_PENDING = "pending"
WEIGHT_EXPORT_CHECKING = "checking"
WEIGHT_EXPORT_SENT = "sent"
WEIGHT_EXPORT_MATCHED = "matched"
WEIGHT_EXPORT_FAILED = "failed"
WEIGHT_EXPORT_SKIPPED = "skipped"
WEIGHT_EXPORT_CONFLICT = "conflict"
WEIGHT_EXPORT_UNVERIFIED = "unverified"
WEIGHT_EXPORT_DELETE_PENDING = "delete_pending"
WEIGHT_EXPORT_DELETE_CHECKING = "delete_checking"
WEIGHT_EXPORT_DELETE_FAILED = "delete_failed"
WEIGHT_EXPORT_DELETED = "deleted"


class GarminDaily(Base, InsightsMixin, TimestampMixin):
    """The day's Garmin recovery + activity snapshot (one row per date)."""

    __tablename__ = "garmin_daily"
    __table_args__ = (
        insights_index(__tablename__),
        # One daily row per date; a re-sync (or the HAE backup) upserts it.
        UniqueConstraint("date", name="uq_garmin_daily_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Sleep ───────────────────────────────────────────────────────────────────
    sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deep_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    light_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rem_sleep_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    awake_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sleep_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sleep_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    awake_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    restless_moments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_sleep_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_sleep_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spo2_lowest: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    respiration_lowest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    respiration_highest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    body_battery_change: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    breathing_disruption: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sleep_need_actual: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The night's two *interval* series. Unlike the point series in
    # ``garmin_intraday``, these are spans (start/end/what) — a couple of dozen a
    # night — so a JSONB column keeps them on the night's own row instead of
    # inventing a second tall table for ~20 rows.
    # ``[{"start", "end", "stage"}]`` — the hypnogram (deep/light/rem/awake).
    sleep_stages: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)
    # ``[{"start", "end", "value"}]`` — breathing-disruption spans (0 = undisturbed).
    breathing_events: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)

    # ── Heart / HRV / respiration ───────────────────────────────────────────────
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hrv_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hrv_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    avg_respiration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spo2_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Stress / Body Battery ───────────────────────────────────────────────────
    avg_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    body_battery_high: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    body_battery_low: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Activity / energy ───────────────────────────────────────────────────────
    steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    floors_climbed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bmr_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    intensity_minutes_moderate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    intensity_minutes_vigorous: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Training ────────────────────────────────────────────────────────────────
    training_readiness: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vo2max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    acute_load: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    load_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class GarminActivity(Base, InsightsMixin, TimestampMixin):
    """A recorded sport activity (run, ride, strength, …)."""

    __tablename__ = "garmin_activities"
    __table_args__ = (
        insights_index(__tablename__),
        UniqueConstraint("external_id", name="uq_garmin_activities_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Per-activity detail ───────────────────────────────────────────────────
    # Scalars read from the activity summary; the two JSONB arrays come from the
    # best-effort per-activity detail calls (HR zones + splits). All nullable —
    # a strength session has no elevation/power/splits, an outdoor run does.
    elevation_gain_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_power: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    training_effect_aerobic: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_effect_anaerobic: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # ``[{"zone", "secs", "low_hr"}]`` — seconds spent in each HR zone.
    hr_zone_seconds: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)
    # ``[{"index", "distance_m", "duration_s", "avg_hr", "max_hr", "avg_speed_mps"}]``
    splits: Mapped[Optional[Any]] = mapped_column(_JSON_TYPE, nullable=True)


class GarminIntraday(Base, InsightsMixin, TimestampMixin):
    """One within-day sample of one series.

    ``garmin_daily`` keeps the day's *summary* of stress, Body Battery and sleep
    (avg, max, high/low); this keeps the curves those numbers were reduced from —
    ~480 samples per whole-day series, plus the night's seven series — which is
    what makes "when did the stress spike" and "when did SpO2 dip" answerable at
    all.

    Deliberately tall/generic (``series_type`` + ``ts`` + ``value``) rather than a
    wide row, which is what let the nightly series join the whole-day ones
    with no schema change at all. A day+series is rebuilt wholesale on re-import
    (delete then insert), which is why there's no unique constraint to upsert
    against.

    ``date`` is the date of the **daily row the samples belong to**, not
    necessarily each sample's own calendar day: a night's series start on the
    previous evening but file under the night's date, so one night reads as one
    unit rather than two halves.
    """

    __tablename__ = "garmin_intraday"
    __table_args__ = (
        insights_index(__tablename__),
        # "This series over a date range" — the chart/MCP read path.
        Index("ix_garmin_intraday_series_date", "series_type", "date"),
        # "Everything recorded on this day, in order" — the day-detail read path,
        # and the (date, series_type) prefix the re-import delete scans.
        Index("ix_garmin_intraday_date_ts", "date", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # One of the SERIES_* constants above.
    series_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # Local naive wall-clock moment of the sample (Garmin ships epoch ms).
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class GarminWeightExport(Base, TimestampMixin):
    """Transactional outbox for local weight writes to Garmin Connect.

    There is one row per date rather than per ``WeightLog`` revision.  When the
    active local value for a date changes, the same outbox row retains the
    ``remote_sample_pk`` needed to replace only a Garmin entry that Vitals owns.
    """

    __tablename__ = "garmin_weight_exports"
    __table_args__ = (
        UniqueConstraint("date", name="uq_garmin_weight_exports_date"),
        CheckConstraint(
            "weight_kg > 0", name="ck_garmin_weight_exports_weight_positive"
        ),
        Index("ix_garmin_weight_exports_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    weight_log_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("weight_logs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    # Local naive wall-clock time; Garmin's client converts it with Config.timezone.
    measured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Exact GMT epoch sent with the current POST marker. Persisting it makes a
    # 204/read-back reconciliation stable even if the configured timezone changes
    # before Garmin exposes the new sample.
    dispatch_timestamp_ms: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=WEIGHT_EXPORT_PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ``samplePk`` is opaque in our code even when Garmin currently emits a number.
    remote_sample_pk: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    remote_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # True only when ``samplePk`` came from the POST itself or its strict
    # timestamp/source/weight correlation marker. Corrections may delete an owned
    # record, but never a pre-existing/manual Garmin record.
    remote_owned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
