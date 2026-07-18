"""HRT cycle items: per-item start offset

``start_offset_days`` anchors an item's schedule grid at
``cycle.start_date + offset`` instead of the cycle start — the missing
primitive for week-staggered multi-compound courses (e.g. an oral from
week 5, HCG weeks 5-9, PCT weeks 11-13).

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hrt_cycle_items",
        sa.Column(
            "start_offset_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("hrt_cycle_items", "start_offset_days")
