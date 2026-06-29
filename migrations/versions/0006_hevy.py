"""Module 5: hevy_workouts, hevy_exercises, hevy_sets

The workout is the dated "log" row (InsightsMixin trio + (domain,date) index +
the Hevy id as a unique upsert key, linked to its raw_payloads row). Exercises
and sets are structural children (FK + cascade) hanging off it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
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
    # ── hevy_workouts ──────────────────────────────────────────────────────────
    op.create_table(
        "hevy_workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("hevy_updated_at", sa.DateTime(), nullable=True),
        sa.Column("program", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_hevy_workouts_external_id"),
    )
    _insights_indexes("hevy_workouts")

    # ── hevy_exercises ─────────────────────────────────────────────────────────
    op.create_table(
        "hevy_exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column("exercise_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("exercise_template_id", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("superset_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["workout_id"], ["hevy_workouts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hevy_exercises_template", "hevy_exercises", ["exercise_template_id"])
    op.create_index("ix_hevy_exercises_workout", "hevy_exercises", ["workout_id"])

    # ── hevy_sets ──────────────────────────────────────────────────────────────
    op.create_table(
        "hevy_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("set_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("set_type", sa.String(16), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["exercise_id"], ["hevy_exercises.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hevy_sets_exercise", "hevy_sets", ["exercise_id"])


def downgrade() -> None:
    op.drop_index("ix_hevy_sets_exercise", table_name="hevy_sets")
    op.drop_table("hevy_sets")

    op.drop_index("ix_hevy_exercises_workout", table_name="hevy_exercises")
    op.drop_index("ix_hevy_exercises_template", table_name="hevy_exercises")
    op.drop_table("hevy_exercises")

    for idx in ("ix_hevy_workouts_domain_date", "ix_hevy_workouts_domain", "ix_hevy_workouts_date"):
        op.drop_index(idx, table_name="hevy_workouts")
    op.drop_table("hevy_workouts")
