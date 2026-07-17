"""garmin_activities — per-activity detail columns

Deeper capture for each recorded activity: elevation gain, average power, the
aerobic/anaerobic training-effect scores, and two variable-shape JSONB arrays
for seconds-in-HR-zone and per-lap splits (from the best-effort per-activity
detail calls). All nullable — a strength session carries none of these, an
outdoor run/ride carries most. Full detail bundle also kept in ``raw_payloads``.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("garmin_activities", sa.Column("elevation_gain_m", sa.Float(), nullable=True))
    op.add_column("garmin_activities", sa.Column("avg_power", sa.Integer(), nullable=True))
    op.add_column("garmin_activities", sa.Column("training_effect_aerobic", sa.Float(), nullable=True))
    op.add_column("garmin_activities", sa.Column("training_effect_anaerobic", sa.Float(), nullable=True))
    op.add_column("garmin_activities", sa.Column("hr_zone_seconds", postgresql.JSONB(), nullable=True))
    op.add_column("garmin_activities", sa.Column("splits", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_activities", "splits")
    op.drop_column("garmin_activities", "hr_zone_seconds")
    op.drop_column("garmin_activities", "training_effect_anaerobic")
    op.drop_column("garmin_activities", "training_effect_aerobic")
    op.drop_column("garmin_activities", "avg_power")
    op.drop_column("garmin_activities", "elevation_gain_m")
