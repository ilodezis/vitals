"""Module 7: lab_results, lab_markers

lab_results is the dated measurement row (InsightsMixin trio + (domain,date) and
(marker,date) indexes, linked to its raw_payloads row). lab_markers is the lean
per-marker catalog (tier / retest interval / defer_until).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
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
    # ── lab_results ────────────────────────────────────────────────────────────
    op.create_table(
        "lab_results",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("marker", sa.String(128), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("ref_low", sa.Float(), nullable=True),
        sa.Column("ref_high", sa.Float(), nullable=True),
        sa.Column("flag", sa.String(16), nullable=True),
        sa.Column("lab_name", sa.String(128), nullable=True),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("lab_results")
    op.create_index("ix_lab_results_marker_date", "lab_results", ["marker", "date"])

    # ── lab_markers (catalog) ──────────────────────────────────────────────────
    op.create_table(
        "lab_markers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'labs'")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("ref_low", sa.Float(), nullable=True),
        sa.Column("ref_high", sa.Float(), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("retest_interval_days", sa.Integer(), nullable=True),
        sa.Column("defer_until", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lab_markers_name", "lab_markers", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_lab_markers_name", table_name="lab_markers")
    op.drop_table("lab_markers")

    op.drop_index("ix_lab_results_marker_date", table_name="lab_results")
    for idx in ("ix_lab_results_domain_date", "ix_lab_results_domain", "ix_lab_results_date"):
        op.drop_index(idx, table_name="lab_results")
    op.drop_table("lab_results")
