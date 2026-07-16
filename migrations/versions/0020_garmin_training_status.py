"""garmin_daily — training status columns

Garmin's ``get_training_status`` (load/recovery balance + VO2max trend,
computed server-side): the feedback phrase (PRODUCTIVE/MAINTAINING/
RECOVERY/...), acute training load, and the acute:chronic workload ratio.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("garmin_daily", sa.Column("training_status", sa.String(32), nullable=True))
    op.add_column("garmin_daily", sa.Column("acute_load", sa.Float(), nullable=True))
    op.add_column("garmin_daily", sa.Column("load_ratio", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("garmin_daily", "load_ratio")
    op.drop_column("garmin_daily", "acute_load")
    op.drop_column("garmin_daily", "training_status")
