"""supplement_periods — when each supplement was started and stopped

The catalog kept only an ``active`` flag, so switching a supplement off erased when
it had been switched on. One row per stretch of taking it: ``date`` is the day it
started, ``end_date`` the day it stopped (null while still taken).

Backfill: every currently active supplement gets one open period from the day its
catalog row was created, marked ``source='inferred'`` — the real start may be
earlier, and the row says so. Inactive rows get nothing: when they ran is unknown.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplement_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column(
            "source", sa.String(32), nullable=False, server_default=sa.text("'manual'")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("supplement_id", sa.Integer(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["supplement_id"], ["supplements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplement_periods_date", "supplement_periods", ["date"])
    op.create_index("ix_supplement_periods_domain", "supplement_periods", ["domain"])
    op.create_index(
        "ix_supplement_periods_domain_date", "supplement_periods", ["domain", "date"]
    )
    op.create_index(
        "ix_supplement_periods_supplement", "supplement_periods", ["supplement_id"]
    )

    op.execute(
        """
        INSERT INTO supplement_periods (supplement_id, date, end_date, domain, source)
        SELECT id, CAST(created_at AS DATE), NULL, 'supplements', 'inferred'
        FROM supplements
        WHERE active
        """
    )


def downgrade() -> None:
    op.drop_index("ix_supplement_periods_supplement", table_name="supplement_periods")
    op.drop_index("ix_supplement_periods_domain_date", table_name="supplement_periods")
    op.drop_index("ix_supplement_periods_domain", table_name="supplement_periods")
    op.drop_index("ix_supplement_periods_date", table_name="supplement_periods")
    op.drop_table("supplement_periods")
