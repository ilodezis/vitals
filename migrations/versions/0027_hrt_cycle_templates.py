"""HRT cycle templates: hrt_cycle_templates, hrt_cycle_template_items

A template is a date-free, relative snapshot of a cycle plan (kind + one item
per compound with its start offset and schedule). Saved from an existing cycle
or imported from portable JSON; materialized into a real cycle at a chosen
start date.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "hrt_cycle_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'hrt'")),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hrt_cycle_templates_name", "hrt_cycle_templates", ["name"])

    op.create_table(
        "hrt_cycle_template_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("compound_key", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False, server_default=sa.text("'mg'")),
        sa.Column("start_offset_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("schedule", _JSON_TYPE, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_id"], ["hrt_cycle_templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hrt_cycle_template_items_template", "hrt_cycle_template_items", ["template_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_hrt_cycle_template_items_template", table_name="hrt_cycle_template_items")
    op.drop_table("hrt_cycle_template_items")
    op.drop_index("ix_hrt_cycle_templates_name", table_name="hrt_cycle_templates")
    op.drop_table("hrt_cycle_templates")
