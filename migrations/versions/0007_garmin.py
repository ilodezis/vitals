"""Module 6: garmin_daily, garmin_activities

garmin_daily is one wide nullable row per date (the day's recovery + activity
metrics), unique on date, linked to its raw_payloads row. garmin_activities are
recorded sport sessions keyed by Garmin's activity id. Both carry the InsightsMixin
trio + (domain, date) index.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insights_columns() -> list:
    return [
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    ]


def _insights_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_date", table, ["date"])
    op.create_index(f"ix_{table}_domain", table, ["domain"])
    op.create_index(f"ix_{table}_domain_date", table, ["domain", "date"])


def upgrade() -> None:
    # ── garmin_daily ───────────────────────────────────────────────────────────
    op.create_table(
        "garmin_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        # Sleep
        sa.Column("sleep_seconds", sa.Integer(), nullable=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("deep_sleep_seconds", sa.Integer(), nullable=True),
        sa.Column("light_sleep_seconds", sa.Integer(), nullable=True),
        sa.Column("rem_sleep_seconds", sa.Integer(), nullable=True),
        sa.Column("awake_seconds", sa.Integer(), nullable=True),
        # Heart / HRV / respiration
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("min_hr", sa.Integer(), nullable=True),
        sa.Column("hrv_avg", sa.Float(), nullable=True),
        sa.Column("hrv_status", sa.String(32), nullable=True),
        sa.Column("avg_respiration", sa.Float(), nullable=True),
        sa.Column("spo2_avg", sa.Float(), nullable=True),
        # Stress / Body Battery
        sa.Column("avg_stress", sa.Integer(), nullable=True),
        sa.Column("max_stress", sa.Integer(), nullable=True),
        sa.Column("body_battery_high", sa.Integer(), nullable=True),
        sa.Column("body_battery_low", sa.Integer(), nullable=True),
        # Activity / energy
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("floors_climbed", sa.Integer(), nullable=True),
        sa.Column("active_calories", sa.Integer(), nullable=True),
        sa.Column("bmr_calories", sa.Integer(), nullable=True),
        sa.Column("total_calories", sa.Integer(), nullable=True),
        sa.Column("intensity_minutes_moderate", sa.Integer(), nullable=True),
        sa.Column("intensity_minutes_vigorous", sa.Integer(), nullable=True),
        # Training
        sa.Column("training_readiness", sa.Integer(), nullable=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_garmin_daily_date"),
    )
    _insights_indexes("garmin_daily")

    # ── garmin_activities ──────────────────────────────────────────────────────
    op.create_table(
        "garmin_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("activity_type", sa.String(64), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_garmin_activities_external_id"),
    )
    _insights_indexes("garmin_activities")


def downgrade() -> None:
    for idx in ("ix_garmin_activities_domain_date", "ix_garmin_activities_domain", "ix_garmin_activities_date"):
        op.drop_index(idx, table_name="garmin_activities")
    op.drop_table("garmin_activities")

    for idx in ("ix_garmin_daily_domain_date", "ix_garmin_daily_domain", "ix_garmin_daily_date"):
        op.drop_index(idx, table_name="garmin_daily")
    op.drop_table("garmin_daily")
