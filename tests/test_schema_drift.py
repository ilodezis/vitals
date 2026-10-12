"""The models and the migrations must build the same database.

Tests build the schema with ``create_all`` from the models; production builds it
with Alembic. Where the two disagreed, every test ran against a schema production
did not have: ``skincare_products.schedule_days`` was JSONB here and JSON there,
and two indexes existed only in migrations. Foreign keys pointing at
``raw_payloads`` and ``hrt_compounds`` had no index at all, so each delete of a
referenced row scanned the referencing table.
"""
from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

import vitals.models  # noqa: F401 — register all tables
from vitals.models.base import Base

migration = importlib.import_module("migrations.versions.0037_schema_drift_and_fk_indexes")

DRIFTED_INDEXES = {
    ("conflict_rules", "ix_conflict_rules_active", ("active",)),
    ("weekly_digests", "ix_weekly_digests_kind_date", ("kind", "date")),
}


def _indexes(table_name: str) -> dict[str, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {ix.name: tuple(c.name for c in ix.columns) for ix in table.indexes}


@pytest.mark.parametrize("table, column", migration._FK_INDEXES)
def test_every_foreign_key_the_migration_indexes_is_indexed_in_the_model(table, column):
    assert _indexes(table).get(f"ix_{table}_{column}") == (column,)


@pytest.mark.parametrize("table, name, columns", sorted(DRIFTED_INDEXES))
def test_indexes_from_migrations_are_declared_in_the_models(table, name, columns):
    assert _indexes(table).get(name) == columns


def test_schedule_days_is_jsonb_on_postgres():
    column = Base.metadata.tables["skincare_products"].c.schedule_days
    assert column.type.compile(dialect=postgresql.dialect()) == "JSONB"


def _schedule_days_type(conn) -> str:
    return conn.execute(sa.text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'skincare_products' AND column_name = 'schedule_days'"
    )).scalar_one()


def _index_names(conn) -> set[str]:
    return set(conn.execute(sa.text("SELECT indexname FROM pg_indexes")).scalars())


def _round_trip(conn) -> dict:
    conn.execute(sa.text(
        "INSERT INTO skincare_products (name, type, schedule_days) "
        "VALUES ('Tretinoin', 'retinoid', '[1, 3, 5]')"
    ))
    ops = Operations(MigrationContext.configure(conn))
    original_op = migration.op
    migration.op = ops
    try:
        migration.downgrade()
        after_down = (_schedule_days_type(conn), _index_names(conn))
        migration.upgrade()
        after_up = (_schedule_days_type(conn), _index_names(conn))
    finally:
        migration.op = original_op
    days = conn.execute(sa.text("SELECT schedule_days FROM skincare_products")).scalar_one()
    return {"down": after_down, "up": after_up, "days": days}


@pytest.mark.integration
async def test_migration_round_trips_on_postgres(db_session):
    fk_names = {f"ix_{t}_{c}" for t, c in migration._FK_INDEXES}
    conn = await db_session.connection()
    result = await conn.run_sync(_round_trip)

    down_type, down_indexes = result["down"]
    assert down_type == "json"
    assert not fk_names & down_indexes

    up_type, up_indexes = result["up"]
    assert up_type == "jsonb"
    assert fk_names <= up_indexes
    assert result["days"] == [1, 3, 5]
