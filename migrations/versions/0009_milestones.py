"""Module 10: milestones, weekly_digests

milestones is a goal-card catalog (related domain, target, deadline, status).
weekly_digests is the dated AI-narrative artifact (InsightsMixin trio +
(domain,date) index), keeping the structured context it was built from in JSONB.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_TYPE = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain", sa.String(32), nullable=False, server_default=sa.text("'weight'")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("target_unit", sa.String(32), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_milestones_status", "milestones", ["status"])

    op.create_table(
        "weekly_digests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'scheduler'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_json", _JSON_TYPE, nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weekly_digests_date", "weekly_digests", ["date"])
    op.create_index("ix_weekly_digests_domain", "weekly_digests", ["domain"])
    op.create_index("ix_weekly_digests_domain_date", "weekly_digests", ["domain", "date"])


def downgrade() -> None:
    for idx in ("ix_weekly_digests_domain_date", "ix_weekly_digests_domain", "ix_weekly_digests_date"):
        op.drop_index(idx, table_name="weekly_digests")
    op.drop_table("weekly_digests")

    op.drop_index("ix_milestones_status", table_name="milestones")
    op.drop_table("milestones")
