"""noise_markers — add direction column

Tracks *which way* a noise period distorts the scale weight vs the real
fat trend, so the AI digest can correctly interpret the bias.

  UP      = scale weight inflated (creatine loading, sodium spike,
             menstrual retention) → real fat-loss is better than raw numbers.
  DOWN    = scale weight deflated (dehydration, illness) → situation is worse.
  NULL    = legacy / unknown (treated as NEUTRAL by the digest builder).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "noise_markers",
        sa.Column("direction", sa.String(16), nullable=True),
    )

    # Best-effort back-fill: existing creatine / sodium / water-retention
    # entries almost certainly represent an UP distortion (scale inflated).
    # Any row whose reason text contains these keywords gets direction='up'.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE noise_markers
               SET direction = 'up'
             WHERE direction IS NULL
               AND (
                   lower(reason) LIKE '%креатин%'
                OR lower(reason) LIKE '%creatine%'
                OR lower(reason) LIKE '%соль%'
                OR lower(reason) LIKE '%sodium%'
                OR lower(reason) LIKE '%вода%'
                OR lower(reason) LIKE '%water%'
               )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("noise_markers", "direction")
