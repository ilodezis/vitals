"""Body composition — body_scans + body_scan_metrics (InBody / МедАсс BIA)

A scan is a dated log row (InsightsMixin trio, domain='body_comp') with the
analyzer device, an optional original-sheet photo key, and a link to the raw
vision payload. Its metrics are generic key/value children (FK + cascade) so any
device's full parameter set is captured.

Also merges ``body_comp: true`` into the app_settings ``enabled_modules`` row so
the optional module is visible immediately after deploy (owner-requested feature;
still toggleable off in Settings).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "body_scans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("device", sa.String(64), nullable=True),
        sa.Column("file_key", sa.String(512), nullable=True),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_body_scans_date", "body_scans", ["date"])
    op.create_index("ix_body_scans_domain", "body_scans", ["domain"])
    op.create_index("ix_body_scans_domain_date", "body_scans", ["domain", "date"])
    op.create_index("ix_body_scans_raw_payload_id", "body_scans", ["raw_payload_id"])

    op.create_table(
        "body_scan_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("metric_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("ref_low", sa.Float(), nullable=True),
        sa.Column("ref_high", sa.Float(), nullable=True),
        sa.Column("segment", sa.String(16), nullable=True),
        sa.Column("category", sa.String(24), nullable=False, server_default=sa.text("'other'")),
        sa.ForeignKeyConstraint(["scan_id"], ["body_scans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_body_scan_metrics_scan", "body_scan_metrics", ["scan_id"])
    op.create_index("ix_body_scan_metrics_key", "body_scan_metrics", ["metric_key"])

    # ── Data migration: add body_comp to enabled_modules ──────────────────────
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict) and "body_comp" not in current:
            current["body_comp"] = True
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )


def downgrade() -> None:
    # Remove body_comp from enabled_modules
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        import json
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict):
            current.pop("body_comp", None)
            conn.execute(
                sa.text(
                    "UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"
                ),
                {"val": json.dumps(current)},
            )

    op.drop_table("body_scan_metrics")
    op.drop_table("body_scans")
