"""HRT/TRT domain: hrt_compounds, hrt_compound_components, hrt_doses, hrt_side_effects

The compound catalog (hrt_compounds) is a reference table like supplements —
no InsightsMixin date. It's seeded from vitals/data/hrt_compounds.yaml by
hrt_catalog.sync_catalog on startup, keyed on the unique `key` slug. Doses and
side effects are point metrics (InsightsMixin trio + composite index). Doses
reference a compound by FK (SET NULL — deleting a catalog row keeps history) and
snapshot its stable key, and carry grey-market provenance (brand/lab/batch/
measured concentration) as plain columns.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


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
    # ── hrt_compounds (molecule catalog, reference — no date) ───────────────────
    op.create_table(
        "hrt_compounds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'hrt'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("name_ru", sa.String(128), nullable=True),
        sa.Column("compound_class", sa.String(32), nullable=False),
        sa.Column("ester", sa.String(32), nullable=True),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("dose_unit", sa.String(8), nullable=False, server_default=sa.text("'mg'")),
        sa.Column("conc_mg_ml", sa.Float(), nullable=True),
        sa.Column("tablet_mg", sa.Float(), nullable=True),
        sa.Column("half_life_hours", sa.Float(), nullable=True),
        sa.Column("active_fraction", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("aromatizes", sa.String(16), nullable=True),
        sa.Column("aliases", _JSON_TYPE, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hrt_compounds_key", "hrt_compounds", ["key"], unique=True)
    op.create_index("ix_hrt_compounds_active", "hrt_compounds", ["active"])
    op.create_index("ix_hrt_compounds_class", "hrt_compounds", ["compound_class"])

    # ── hrt_compound_components (blend ester breakdown) ─────────────────────────
    op.create_table(
        "hrt_compound_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("compound_id", sa.Integer(), nullable=False),
        sa.Column("ester", sa.String(32), nullable=False),
        sa.Column("mg", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["compound_id"], ["hrt_compounds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hrt_compound_components_compound", "hrt_compound_components", ["compound_id"]
    )

    # ── hrt_doses (administration log, point metric) ────────────────────────────
    op.create_table(
        "hrt_doses",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("compound_id", sa.Integer(), nullable=True),
        sa.Column("compound_key", sa.String(64), nullable=False),
        sa.Column("dose", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False, server_default=sa.text("'mg'")),
        sa.Column("volume_ml", sa.Float(), nullable=True),
        sa.Column("concentration_mg_ml", sa.Float(), nullable=True),
        sa.Column("brand", sa.String(64), nullable=True),
        sa.Column("lab", sa.String(64), nullable=True),
        sa.Column("batch", sa.String(64), nullable=True),
        sa.Column("site", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["compound_id"], ["hrt_compounds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("dose > 0", name="ck_hrt_doses_dose_positive"),
    )
    _insights_indexes("hrt_doses")
    op.create_index("ix_hrt_doses_compound_key", "hrt_doses", ["compound_key"])

    # ── hrt_side_effects (symptom log 1-5) ──────────────────────────────────────
    op.create_table(
        "hrt_side_effects",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("effect_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "severity >= 1 AND severity <= 5", name="ck_hrt_side_effects_severity_range"
        ),
    )
    _insights_indexes("hrt_side_effects")


def downgrade() -> None:
    for idx in ("ix_hrt_side_effects_domain_date", "ix_hrt_side_effects_domain", "ix_hrt_side_effects_date"):
        op.drop_index(idx, table_name="hrt_side_effects")
    op.drop_table("hrt_side_effects")

    op.drop_index("ix_hrt_doses_compound_key", table_name="hrt_doses")
    for idx in ("ix_hrt_doses_domain_date", "ix_hrt_doses_domain", "ix_hrt_doses_date"):
        op.drop_index(idx, table_name="hrt_doses")
    op.drop_table("hrt_doses")

    op.drop_index("ix_hrt_compound_components_compound", table_name="hrt_compound_components")
    op.drop_table("hrt_compound_components")

    op.drop_index("ix_hrt_compounds_class", table_name="hrt_compounds")
    op.drop_index("ix_hrt_compounds_active", table_name="hrt_compounds")
    op.drop_index("ix_hrt_compounds_key", table_name="hrt_compounds")
    op.drop_table("hrt_compounds")
