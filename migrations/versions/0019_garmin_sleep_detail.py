"""garmin_daily — sleep detail columns

Further parsing of the already-downloaded Garmin sleep payload (no new
network calls): bed/wake time, awakenings, in-sleep stress/HR, night-low
SpO2, respiration range, overnight Body Battery change, breathing
disruption severity, and next-night sleep need.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("garmin_daily", sa.Column("sleep_start", sa.DateTime(), nullable=True))
    op.add_column("garmin_daily", sa.Column("sleep_end", sa.DateTime(), nullable=True))
    op.add_column("garmin_daily", sa.Column("awake_count", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("restless_moments", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("avg_sleep_stress", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("avg_sleep_hr", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("spo2_lowest", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("respiration_lowest", sa.Float(), nullable=True))
    op.add_column("garmin_daily", sa.Column("respiration_highest", sa.Float(), nullable=True))
    op.add_column("garmin_daily", sa.Column("body_battery_change", sa.Integer(), nullable=True))
    op.add_column("garmin_daily", sa.Column("breathing_disruption", sa.String(16), nullable=True))
    op.add_column("garmin_daily", sa.Column("sleep_need_actual", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_daily", "sleep_need_actual")
    op.drop_column("garmin_daily", "breathing_disruption")
    op.drop_column("garmin_daily", "body_battery_change")
    op.drop_column("garmin_daily", "respiration_highest")
    op.drop_column("garmin_daily", "respiration_lowest")
    op.drop_column("garmin_daily", "spo2_lowest")
    op.drop_column("garmin_daily", "avg_sleep_hr")
    op.drop_column("garmin_daily", "avg_sleep_stress")
    op.drop_column("garmin_daily", "restless_moments")
    op.drop_column("garmin_daily", "awake_count")
    op.drop_column("garmin_daily", "sleep_end")
    op.drop_column("garmin_daily", "sleep_start")
