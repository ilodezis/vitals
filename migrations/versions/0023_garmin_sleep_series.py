"""garmin sleep detail, level B — the night's interval series

The night's *point* series (heart rate, SpO2, respiration, stress, Body Battery,
HRV, movement) need no schema at all: they reuse run 4's generic
``garmin_intraday`` table as new ``series_type`` values. Only the two *interval*
series have nowhere to go — a hypnogram entry is a span (start/end/stage), not a
sample — so they land here as JSONB on the night's own daily row rather than in a
second tall table for ~20 rows a night.

Both nullable: a day without a recorded sleep simply has neither.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("garmin_daily", sa.Column("sleep_stages", postgresql.JSONB(), nullable=True))
    op.add_column("garmin_daily", sa.Column("breathing_events", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_daily", "breathing_events")
    op.drop_column("garmin_daily", "sleep_stages")
