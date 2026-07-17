"""HRT cycles: hrt_cycles, hrt_cycle_items

A cycle is a date range (like glp1_dose_phases) owning one plan item per
compound. An item's ``schedule`` is a JSON list of segments (flat or linear
ramp) that the schedule engine expands into planned administrations off a fixed
grid anchored at the cycle start.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "hrt_cycles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'hrt'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hrt_cycles_range", "hrt_cycles", ["domain", "start_date", "end_date"])

    op.create_table(
        "hrt_cycle_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("cycle_id", sa.Integer(), nullable=False),
        sa.Column("compound_id", sa.Integer(), nullable=True),
        sa.Column("compound_key", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False, server_default=sa.text("'mg'")),
        sa.Column("schedule", _JSON_TYPE, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["cycle_id"], ["hrt_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compound_id"], ["hrt_compounds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hrt_cycle_items_cycle", "hrt_cycle_items", ["cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_hrt_cycle_items_cycle", table_name="hrt_cycle_items")
    op.drop_table("hrt_cycle_items")
    op.drop_index("ix_hrt_cycles_range", table_name="hrt_cycles")
    op.drop_table("hrt_cycles")
