"""Genetics — enforce one row per rsID (partial-unique index).

``genetic_variants.rsid`` had only a plain lookup index, so a re-import or a
manual re-entry of the same rsID could silently create a duplicate row (even
though ``genetics_service.upsert_by_rsid`` assumes at most one). We first
collapse any existing duplicates — keeping the most-recently-inserted row
(``MAX(id)``) per rsID, which carries the freshest genotype — then swap the plain
``ix_genetic_variants_rsid`` index for a partial-unique
``uq_genetic_variant_rsid`` on ``rsid WHERE rsid IS NOT NULL`` (manual rows with
no rsID keep coexisting freely). Mirrors ``vitals/models/genetics.py`` so
``create_all`` (tests) and Alembic build the same constraint.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Data migration: collapse duplicate rsIDs before the unique index ──────
    # Keep the newest row (MAX(id)) per non-null rsid; drop the older duplicates.
    conn.execute(
        sa.text(
            """
            DELETE FROM genetic_variants
            WHERE rsid IS NOT NULL
              AND id NOT IN (
                  SELECT MAX(id)
                  FROM genetic_variants
                  WHERE rsid IS NOT NULL
                  GROUP BY rsid
              )
            """
        )
    )

    op.drop_index("ix_genetic_variants_rsid", table_name="genetic_variants")
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_genetic_variant_rsid
            ON genetic_variants (rsid)
            WHERE rsid IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    # The dedup DELETE is not reversible (the collapsed duplicate rows are gone);
    # only the index change is undone here.
    op.execute(sa.text("DROP INDEX IF EXISTS uq_genetic_variant_rsid"))
    op.create_index("ix_genetic_variants_rsid", "genetic_variants", ["rsid"])
