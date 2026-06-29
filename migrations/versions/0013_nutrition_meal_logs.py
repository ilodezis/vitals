"""Nutrition — meal_logs table with macro tracking

Multiple meals per day, optional KCAL/protein/fat/carbs. Uses the InsightsMixin
trio (date, domain, source) plus eaten_at (wall-clock time within the day).

Also merges ``nutrition: true`` into the app_settings ``enabled_modules`` row so
the module is visible immediately after deploy.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meal_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("eaten_at", sa.Time(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("calories IS NULL OR calories >= 0", name="ck_meal_logs_calories_nonneg"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_logs_date", "meal_logs", ["date"])
    op.create_index("ix_meal_logs_domain", "meal_logs", ["domain"])
    op.create_index("ix_meal_logs_domain_date", "meal_logs", ["domain", "date"])

    # ── Data migration: add nutrition to enabled_modules ──────────────────────
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict) and "nutrition" not in current:
            current["nutrition"] = True
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )


def downgrade() -> None:
    # Remove nutrition from enabled_modules
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict):
            current.pop("nutrition", None)
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )

    op.drop_table("meal_logs")
