"""schema drift and foreign-key indexes

Brings the migrated schema in line with the models, so ``create_all`` (the test
path) and Alembic (production) build the same database:

* ``skincare_products.schedule_days`` was created as JSON while the model declares
  JSONB; it becomes JSONB like every other JSON column.
* ``ix_conflict_rules_active`` and ``ix_weekly_digests_kind_date`` already exist
  here (created in 0001 and 0031); the models now declare them too. Nothing to do
  in this migration for those two.

Postgres does not index a foreign key by itself. Each ``raw_payload_id`` below is
an ``ON DELETE SET NULL`` reference, so deleting one raw payload scanned the whole
referencing table — ``garmin_intraday`` the largest of them. ``compound_id`` on
the HRT log tables is the same pattern. Plain ``CREATE INDEX`` is enough:
migrations run before the app starts, when nothing else writes.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) — index name follows SQLAlchemy's ``index=True`` default.
_FK_INDEXES = (
    ("garmin_intraday", "raw_payload_id"),
    ("garmin_daily", "raw_payload_id"),
    ("garmin_activities", "raw_payload_id"),
    ("hevy_workouts", "raw_payload_id"),
    ("lab_results", "raw_payload_id"),
    ("hrt_doses", "compound_id"),
    ("hrt_cycle_items", "compound_id"),
)


def _name(table: str, column: str) -> str:
    return f"ix_{table}_{column}"


def _set_schedule_days_type(type_name: str) -> None:
    # The '[]' default is typed too; drop it around the change and put it back.
    op.execute("ALTER TABLE skincare_products ALTER COLUMN schedule_days DROP DEFAULT")
    op.execute(
        f"ALTER TABLE skincare_products ALTER COLUMN schedule_days "
        f"TYPE {type_name} USING schedule_days::{type_name}"
    )
    op.execute("ALTER TABLE skincare_products ALTER COLUMN schedule_days SET DEFAULT '[]'")


def upgrade() -> None:
    _set_schedule_days_type("jsonb")
    for table, column in _FK_INDEXES:
        op.create_index(_name(table, column), table, [column])


def downgrade() -> None:
    for table, column in reversed(_FK_INDEXES):
        op.drop_index(_name(table, column), table_name=table)
    _set_schedule_days_type("json")
