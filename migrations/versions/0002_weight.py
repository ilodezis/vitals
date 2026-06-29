"""Phase 1: weight_logs, body_measurements, progress_photos, noise_markers

All log/metric tables carry the InsightsMixin trio (date, domain, source) + a
composite (domain, date) index. weight_logs enforces "one active weight per date"
(manual supersedes Garmin) via a partial unique index on superseded = false.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
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
    # ── weight_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "weight_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("superseded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"], ["raw_payloads.id"],
            name="fk_weight_logs_raw_payload_id", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("weight_logs")
    op.create_index("ix_weight_logs_raw_payload_id", "weight_logs", ["raw_payload_id"])
    # One active (non-superseded) weight per date.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_weight_per_date
            ON weight_logs (date)
            WHERE superseded = false
            """
        )
    )

    # ── body_measurements ──────────────────────────────────────────────────────
    op.create_table(
        "body_measurements",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("neck_cm", sa.Float(), nullable=True),
        sa.Column("waist_cm", sa.Float(), nullable=True),
        sa.Column("hips_cm", sa.Float(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("lbm_kg", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_body_measurement_per_date"),
    )
    _insights_indexes("body_measurements")

    # ── progress_photos ────────────────────────────────────────────────────────
    op.create_table(
        "progress_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        *_insights_columns(),
        sa.Column("file_key", sa.String(512), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _insights_indexes("progress_photos")

    # ── noise_markers (date ranges excluded from trend/regression) ─────────────
    op.create_table(
        "noise_markers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'weight'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_noise_markers_domain_range", "noise_markers", ["domain", "start_date", "end_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_noise_markers_domain_range", table_name="noise_markers")
    op.drop_table("noise_markers")

    for idx in ("ix_progress_photos_domain_date", "ix_progress_photos_domain", "ix_progress_photos_date"):
        op.drop_index(idx, table_name="progress_photos")
    op.drop_table("progress_photos")

    for idx in ("ix_body_measurements_domain_date", "ix_body_measurements_domain", "ix_body_measurements_date"):
        op.drop_index(idx, table_name="body_measurements")
    op.drop_table("body_measurements")

    op.execute(sa.text("DROP INDEX IF EXISTS uq_active_weight_per_date"))
    op.drop_index("ix_weight_logs_raw_payload_id", table_name="weight_logs")
    for idx in ("ix_weight_logs_domain_date", "ix_weight_logs_domain", "ix_weight_logs_date"):
        op.drop_index(idx, table_name="weight_logs")
    op.drop_table("weight_logs")
