"""Guard physical/semantic value ranges with CHECK constraints.

A data-lake feeds cross-domain correlations and auto-AI reports, so junk values
(negative weight, zero dose) must never persist. These mirror the model
``__table_args__`` so ``create_all`` (SQLite tests) and Postgres agree:

  * ``weight_logs.weight_kg > 0``
  * ``glp1_injections.dose_mg > 0``
  * ``glp1_dose_phases.dose_mg > 0``
  * ``glp1_side_effects.severity`` graded 1..5

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_weight_logs_weight_positive", "weight_logs", "weight_kg > 0"
    )
    op.create_check_constraint(
        "ck_glp1_injections_dose_positive", "glp1_injections", "dose_mg > 0"
    )
    op.create_check_constraint(
        "ck_glp1_dose_phases_dose_positive", "glp1_dose_phases", "dose_mg > 0"
    )
    op.create_check_constraint(
        "ck_glp1_side_effects_severity_range",
        "glp1_side_effects",
        "severity >= 1 AND severity <= 5",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_glp1_side_effects_severity_range", "glp1_side_effects", type_="check"
    )
    op.drop_constraint(
        "ck_glp1_dose_phases_dose_positive", "glp1_dose_phases", type_="check"
    )
    op.drop_constraint(
        "ck_glp1_injections_dose_positive", "glp1_injections", type_="check"
    )
    op.drop_constraint(
        "ck_weight_logs_weight_positive", "weight_logs", type_="check"
    )
