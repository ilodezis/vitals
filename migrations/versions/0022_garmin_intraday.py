"""garmin_intraday — within-day stress / Body Battery sample series

The first minute-level table in the project: everything Garmin until now was a
day-level scalar. Tall and generic (series_type + ts + value) so run 5's sleep
series (sleep_hr, sleep_spo2, …) reuse it by adding series_type values only,
with no further migration. A day+series is rebuilt wholesale on re-import, so
there is no unique constraint — the two extra indexes cover the read paths
(one series over a range; one day in order) and the re-import delete.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "garmin_intraday",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload_id", sa.Integer(), nullable=True),
        sa.Column("series_type", sa.String(24), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_garmin_intraday_date", "garmin_intraday", ["date"])
    op.create_index("ix_garmin_intraday_domain", "garmin_intraday", ["domain"])
    op.create_index("ix_garmin_intraday_domain_date", "garmin_intraday", ["domain", "date"])
    op.create_index("ix_garmin_intraday_series_date", "garmin_intraday", ["series_type", "date"])
    op.create_index("ix_garmin_intraday_date_ts", "garmin_intraday", ["date", "ts"])


def downgrade() -> None:
    for idx in (
        "ix_garmin_intraday_date_ts",
        "ix_garmin_intraday_series_date",
        "ix_garmin_intraday_domain_date",
        "ix_garmin_intraday_domain",
        "ix_garmin_intraday_date",
    ):
        op.drop_index(idx, table_name="garmin_intraday")
    op.drop_table("garmin_intraday")
