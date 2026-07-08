"""Timeline — annotations table (manual event flags shown on charts).

Also merges ``timeline: true`` into the app_settings ``enabled_modules`` row so
the optional module is visible immediately after deploy (same pattern as 0015
body_comp — still toggleable off in Settings).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False, server_default=sa.text("'note'")),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_annotations_date", "annotations", ["date"])
    op.create_index("ix_annotations_domain", "annotations", ["domain"])
    op.create_index("ix_annotations_domain_date", "annotations", ["domain", "date"])
    op.create_index("ix_annotations_date_range", "annotations", ["date", "end_date"])

    # ── Data migration: add timeline to enabled_modules ───────────────────────
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict) and "timeline" not in current:
            current["timeline"] = True
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict):
            current.pop("timeline", None)
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )

    op.drop_table("annotations")
