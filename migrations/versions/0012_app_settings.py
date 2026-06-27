"""app_settings — generic single-user key-value config store (JSONB)

Backs runtime-mutable configuration that must change without a container restart.
First consumer: ``enabled_modules`` (dashboard modularity — which optional domains
show in the navigation).

The seed row turns **all** optional modules ON, so an existing install keeps its
current navigation after this migration; the user disables what they don't need
from /settings. The *fail-safe* default (optional OFF) lives in code and only
applies when the row is missing/corrupt — it is intentionally NOT what we seed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors vitals.services.modules_service registry at migration time. Kept literal
# (not imported) so the migration is a frozen snapshot independent of code drift.
_SEED_MODULES = {
    # Core — always on (also force-enabled in code).
    "weight": True,
    "garmin": True,
    "labs": True,
    "reports": True,
    # Optional — seeded ON to preserve the pre-migration navigation.
    "glp1": True,
    "hevy": True,
    "supplements": True,
    "genetics": True,
    "skincare": True,
}


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )

    # Seed the enabled-modules row (timestamps fall back to the server defaults).
    app_settings = sa.table(
        "app_settings",
        sa.column("key", sa.String),
        sa.column("value", postgresql.JSONB),
    )
    op.bulk_insert(
        app_settings,
        [{"key": "enabled_modules", "value": _SEED_MODULES}],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
