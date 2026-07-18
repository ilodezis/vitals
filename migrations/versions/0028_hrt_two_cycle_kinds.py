"""HRT: collapse the five cycle kinds to two

trt_baseline / blast / cruise / bridge all behaved identically apart from the
bloodwork-reminder cadence — five labels, one behavior. Collapse them into
``course`` (any exogenous-hormone protocol); ``pct`` stays distinct because
restarting natural production is a genuinely different mode. The nuance the
old kinds carried belongs in the cycle's free-text name.

Irreversible by nature (the old label is lost), so downgrade keeps the data.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_COURSE_KINDS = ("trt_baseline", "blast", "cruise", "bridge")


def upgrade() -> None:
    for table in ("hrt_cycles", "hrt_cycle_templates"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET kind = 'course' WHERE kind IN :old"
            ).bindparams(sa.bindparam("old", expanding=True, value=list(_OLD_COURSE_KINDS)))
        )


def downgrade() -> None:
    # The original five-way label is gone; 'course'/'pct' remain valid data.
    pass
