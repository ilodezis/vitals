"""environment — the bedroom's air (samples + hourly rollup)

``environment_samples`` takes one row per snapshot a sensor station produces (every
10 s, around the clock). ``(station_id, boot_id, seq)`` is unique, so polling the
same snapshot twice is a no-op. Instants are ``timestamptz`` in UTC; ``date`` is the
local calendar date of ``ts``.

``environment_hourly`` is the rollup the rollup job fills, one row per station-hour,
so a week-long chart reads 168 rows instead of tens of thousands.

The module itself is optional and defaults off, so no ``app_settings`` seed.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insights_columns() -> list[sa.Column]:
    return [
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column(
            "source", sa.String(32), nullable=False, server_default=sa.text("'manual'")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    ]


def _insights_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_date", table, ["date"])
    op.create_index(f"ix_{table}_domain", table, ["domain"])
    op.create_index(f"ix_{table}_domain_date", table, ["domain", "date"])


def upgrade() -> None:
    op.create_table(
        "environment_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("station_id", sa.String(16), nullable=False),
        sa.Column("boot_id", sa.String(16), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "time_basis", sa.String(16), nullable=False, server_default=sa.text("'device'")
        ),
        sa.Column("co2_ppm", sa.SmallInteger(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("humidity_pct", sa.Float(), nullable=True),
        sa.Column("lux_avg", sa.Float(), nullable=True),
        sa.Column("lux_max", sa.Float(), nullable=True),
        sa.Column("quality", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "station_id", "boot_id", "seq", name="uq_environment_samples_snapshot"
        ),
    )
    _insights_indexes("environment_samples")
    op.create_index(
        "ix_environment_samples_station_ts", "environment_samples", ["station_id", "ts"]
    )

    op.create_table(
        "environment_hourly",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("station_id", sa.String(16), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("coverage_pct", sa.Float(), nullable=False),
        sa.Column("co2_mean", sa.Float(), nullable=True),
        sa.Column("co2_min", sa.SmallInteger(), nullable=True),
        sa.Column("co2_max", sa.SmallInteger(), nullable=True),
        sa.Column("co2_p90", sa.Float(), nullable=True),
        sa.Column("temp_mean", sa.Float(), nullable=True),
        sa.Column("temp_min", sa.Float(), nullable=True),
        sa.Column("temp_max", sa.Float(), nullable=True),
        sa.Column("rh_mean", sa.Float(), nullable=True),
        sa.Column("rh_min", sa.Float(), nullable=True),
        sa.Column("rh_max", sa.Float(), nullable=True),
        sa.Column("lux_mean", sa.Float(), nullable=True),
        sa.Column("lux_max", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "station_id", "hour_start", name="uq_environment_hourly_station_hour"
        ),
    )
    _insights_indexes("environment_hourly")


def downgrade() -> None:
    for table in ("environment_hourly", "environment_samples"):
        for idx in (f"ix_{table}_domain_date", f"ix_{table}_domain", f"ix_{table}_date"):
            op.drop_index(idx, table_name=table)
    op.drop_index("ix_environment_samples_station_ts", table_name="environment_samples")
    op.drop_table("environment_hourly")
    op.drop_table("environment_samples")
