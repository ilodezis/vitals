"""Phase 2: glp1_injections, glp1_dose_phases, glp1_side_effects

Injections + side effects carry the InsightsMixin trio (date, domain, source) +
a composite (domain, date) index. Dose phases are date ranges (start/end) that
paint the weight chart overlay and bound the plateau check.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
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
    # ── glp1_injections ────────────────────────────────────────────────────────
    op.create_table(
        "glp1_injections",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("drug", sa.String(32), nullable=False),
        sa.Column("dose_mg", sa.Float(), nullable=False),
        sa.Column("site", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("glp1_injections")

    # ── glp1_dose_phases (date ranges → weight chart overlay) ───────────────────
    op.create_table(
        "glp1_dose_phases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'glp1'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("drug", sa.String(32), nullable=False),
        sa.Column("dose_mg", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_glp1_dose_phases_range", "glp1_dose_phases", ["domain", "start_date", "end_date"]
    )

    # ── glp1_side_effects ──────────────────────────────────────────────────────
    op.create_table(
        "glp1_side_effects",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("effect_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("glp1_side_effects")


def downgrade() -> None:
    for idx in ("ix_glp1_side_effects_domain_date", "ix_glp1_side_effects_domain", "ix_glp1_side_effects_date"):
        op.drop_index(idx, table_name="glp1_side_effects")
    op.drop_table("glp1_side_effects")

    op.drop_index("ix_glp1_dose_phases_range", table_name="glp1_dose_phases")
    op.drop_table("glp1_dose_phases")

    for idx in ("ix_glp1_injections_domain_date", "ix_glp1_injections_domain", "ix_glp1_injections_date"):
        op.drop_index(idx, table_name="glp1_injections")
    op.drop_table("glp1_injections")
