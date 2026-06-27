"""Foundation tables: raw_payloads, system_alerts, conflict_rules

The cross-cutting "Insights Layer" storage that every module builds on:
  * raw_payloads   — central JSONB store (GIN-indexed) for full external responses
  * system_alerts  — info/warn/block ladder, deduped by a partial-unique index on
                     unresolved rows
  * conflict_rules — data-driven cross-domain rules evaluated by conflict_engine

Revision ID: 0001
Revises:
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── raw_payloads — central JSONB store ─────────────────────────────────────
    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_payloads_domain", "raw_payloads", ["domain"])
    op.create_index(
        "ix_raw_payloads_domain_source_external",
        "raw_payloads",
        ["domain", "source", "external_id"],
    )
    # GIN over the JSONB payload for containment / key-existence queries.
    op.create_index(
        "ix_raw_payloads_payload_gin",
        "raw_payloads",
        ["payload"],
        postgresql_using="gin",
    )

    # ── system_alerts — info/warn/block ladder ─────────────────────────────────
    op.create_table(
        "system_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("alert_key", sa.String(128), nullable=False),
        sa.Column("entity_ref", sa.String(128), nullable=False, server_default=sa.text("''")),
        sa.Column("override_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_system_alerts_domain_resolved", "system_alerts", ["domain", "resolved_at"]
    )
    # Dedupe: at most one active (unresolved) alert per (alert_key, entity_ref).
    # Partial unique → raw SQL (idempotent), per the boxly-migration pattern.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_alert_per_key_entity
            ON system_alerts (alert_key, entity_ref)
            WHERE resolved_at IS NULL
            """
        )
    )

    # ── conflict_rules — data-driven cross-domain rules ────────────────────────
    op.create_table(
        "conflict_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("domain_a", sa.String(32), nullable=False),
        sa.Column("condition_a", postgresql.JSONB(), nullable=False),
        sa.Column("domain_b", sa.String(32), nullable=False),
        sa.Column("condition_b", postgresql.JSONB(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conflict_rules_active", "conflict_rules", ["active"])


def downgrade() -> None:
    op.drop_index("ix_conflict_rules_active", table_name="conflict_rules")
    op.drop_table("conflict_rules")

    op.execute(sa.text("DROP INDEX IF EXISTS uq_active_alert_per_key_entity"))
    op.drop_index("ix_system_alerts_domain_resolved", table_name="system_alerts")
    op.drop_table("system_alerts")

    op.drop_index("ix_raw_payloads_payload_gin", table_name="raw_payloads")
    op.drop_index("ix_raw_payloads_domain_source_external", table_name="raw_payloads")
    op.drop_index("ix_raw_payloads_domain", table_name="raw_payloads")
    op.drop_table("raw_payloads")
