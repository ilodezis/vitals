"""Phase 3: supplements, genetic_variants, skincare_logs, skincare_observations

Supplements + genetics are reference tables (domain/source, no per-day date).
Skincare logs/observations are daily (InsightsMixin). Also seeds the three real
cross-domain conflict rules that finally exercise the override flow:

  1. retinoid + peel same evening      (skincare ↔ skincare, block, overridable)
  2. active isotretinoin → no peel     (supplements ↔ skincare, block)
  3. hemochromatosis carrier → no iron (genetics ↔ supplements, block)

Rules are data — they fire only when matching rows exist, so seeding them is safe
on an empty install.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seeded rule messages — also used to delete them on downgrade.
RULE_RETINOID_PEEL = "Ретиноид и пилинг в один вечер — высокий риск раздражения."
RULE_ISOTRETINOIN_PEEL = "Системный изотретиноин активен — химический пилинг противопоказан."
RULE_HEMOCHROMATOSIS_IRON = "Носительство гемохроматоза — препараты железа противопоказаны."


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
    # ── supplements (catalog/reference) ─────────────────────────────────────────
    op.create_table(
        "supplements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'supplements'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("dose", sa.String(64), nullable=True),
        sa.Column("timing", sa.String(64), nullable=True),
        sa.Column("evidence", sa.String(1), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("contraindications", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplements_key", "supplements", ["key"])
    op.create_index("ix_supplements_active", "supplements", ["active"])

    # ── genetic_variants (reference) ────────────────────────────────────────────
    op.create_table(
        "genetic_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'genetics'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("gene", sa.String(64), nullable=False),
        sa.Column("rsid", sa.String(32), nullable=True),
        sa.Column("genotype", sa.String(16), nullable=True),
        sa.Column("marker", sa.String(64), nullable=True),
        sa.Column("impact", sa.String(128), nullable=True),
        sa.Column("impact_domain", sa.String(32), nullable=True),
        sa.Column("interpretation", sa.Text(), nullable=True),
        sa.Column("action_notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_genetic_variants_marker", "genetic_variants", ["marker"])
    op.create_index("ix_genetic_variants_rsid", "genetic_variants", ["rsid"])

    # ── skincare_logs (daily checklist) ─────────────────────────────────────────
    op.create_table(
        "skincare_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("retinoid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("azelaic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("peel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("niacinamide_spf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("moisturizer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("skincare_logs")

    # ── skincare_observations (daily graded state) ──────────────────────────────
    op.create_table(
        "skincare_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("inflammation", sa.Integer(), nullable=True),
        sa.Column("pih", sa.Integer(), nullable=True),
        sa.Column("zone", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("skincare_observations")

    # ── seed cross-domain conflict rules ────────────────────────────────────────
    rules = sa.table(
        "conflict_rules",
        sa.column("rule_type", sa.String),
        sa.column("domain_a", sa.String),
        sa.column("condition_a", sa.JSON),
        sa.column("domain_b", sa.String),
        sa.column("condition_b", sa.JSON),
        sa.column("severity", sa.String),
        sa.column("message", sa.Text),
        sa.column("active", sa.Boolean),
    )
    op.bulk_insert(
        rules,
        [
            {
                "rule_type": "hard_block",
                "domain_a": "skincare",
                "condition_a": {"retinoid": True},
                "domain_b": "skincare",
                "condition_b": {"peel": True},
                "severity": "block",
                "message": RULE_RETINOID_PEEL,
                "active": True,
            },
            {
                "rule_type": "hard_block",
                "domain_a": "supplements",
                "condition_a": {"key": "isotretinoin", "active": True},
                "domain_b": "skincare",
                "condition_b": {"peel": True},
                "severity": "block",
                "message": RULE_ISOTRETINOIN_PEEL,
                "active": True,
            },
            {
                "rule_type": "hard_block",
                "domain_a": "genetics",
                "condition_a": {"marker": "hemochromatosis_carrier"},
                "domain_b": "supplements",
                "condition_b": {"key": "iron", "active": True},
                "severity": "block",
                "message": RULE_HEMOCHROMATOSIS_IRON,
                "active": True,
            },
        ],
    )


def downgrade() -> None:
    rules = sa.table("conflict_rules", sa.column("message", sa.Text))
    for msg in (RULE_RETINOID_PEEL, RULE_ISOTRETINOIN_PEEL, RULE_HEMOCHROMATOSIS_IRON):
        op.execute(rules.delete().where(rules.c.message == msg))

    for idx in ("ix_skincare_observations_domain_date", "ix_skincare_observations_domain", "ix_skincare_observations_date"):
        op.drop_index(idx, table_name="skincare_observations")
    op.drop_table("skincare_observations")

    for idx in ("ix_skincare_logs_domain_date", "ix_skincare_logs_domain", "ix_skincare_logs_date"):
        op.drop_index(idx, table_name="skincare_logs")
    op.drop_table("skincare_logs")

    op.drop_index("ix_genetic_variants_rsid", table_name="genetic_variants")
    op.drop_index("ix_genetic_variants_marker", table_name="genetic_variants")
    op.drop_table("genetic_variants")

    op.drop_index("ix_supplements_active", table_name="supplements")
    op.drop_index("ix_supplements_key", table_name="supplements")
    op.drop_table("supplements")
