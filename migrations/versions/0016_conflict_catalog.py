"""Conflict engine — curated rule catalog columns + dermatology flag expansion.

``conflict_rules`` gains ``code`` (stable slug the YAML catalog upserts
against — see ``conflict_catalog.sync_catalog``), ``category``, ``source`` and
``evidence`` (browsable metadata for ``/interactions``). The 3 rules seeded by
migration 0004 get a ``code`` backfilled by their known ``message`` text so the
very first ``sync_catalog`` run recognizes them as already-present rows
(preserving anything the user already toggled) instead of inserting
duplicates.

Also adds ``vitamin_c``/``benzoyl_peroxide`` to ``skincare_logs`` — the
dermatology rule set needs them (retinoid/peel vs. these) and the checklist
previously had no way to represent either being applied.

Finally merges ``interactions: true`` into ``enabled_modules`` (same pattern as
0015's ``body_comp``): the conflict engine has been silent/invisible until now,
so the new browser is surfaced by default rather than behind an extra toggle.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-02
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Message text the 3 rules were seeded with in 0004 — used to backfill `code`
# without disturbing the rows (matches conflict_catalog's codes for the same
# rules in vitals/data/conflict_rules.yaml, so the first sync recognizes them).
_CODE_BY_MESSAGE = {
    "Ретиноид и пилинг в один вечер — высокий риск раздражения.": "derm_retinoid_peel_same_day",
    "Системный изотретиноин активен — химический пилинг противопоказан.": "derm_isotretinoin_peel_contraindicated",
    "Носительство гемохроматоза — препараты железа противопоказаны.": "pgx_hemochromatosis_iron_block",
}


def upgrade() -> None:
    op.add_column("conflict_rules", sa.Column("code", sa.String(96), nullable=True))
    op.add_column("conflict_rules", sa.Column("category", sa.String(32), nullable=True))
    op.add_column("conflict_rules", sa.Column("source", sa.Text(), nullable=True))
    op.add_column("conflict_rules", sa.Column("evidence", sa.String(1), nullable=True))
    op.create_index("ix_conflict_rules_code", "conflict_rules", ["code"], unique=True)

    conn = op.get_bind()
    rules = sa.table(
        "conflict_rules", sa.column("id", sa.Integer), sa.column("message", sa.Text), sa.column("code", sa.String)
    )
    for message, code in _CODE_BY_MESSAGE.items():
        conn.execute(rules.update().where(rules.c.message == message).values(code=code))

    op.add_column(
        "skincare_logs",
        sa.Column("vitamin_c", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "skincare_logs",
        sa.Column("benzoyl_peroxide", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # ── Data migration: surface the new /interactions browser by default ──────
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict) and "interactions" not in current:
            current["interactions"] = True
            conn.execute(
                sa.text("UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"),
                {"val": json.dumps(current)},
            )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'enabled_modules'")
    ).fetchone()
    if row is not None:
        current = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(current, dict):
            current.pop("interactions", None)
            conn.execute(
                sa.text("UPDATE app_settings SET value = :val WHERE key = 'enabled_modules'"),
                {"val": json.dumps(current)},
            )

    op.drop_column("skincare_logs", "benzoyl_peroxide")
    op.drop_column("skincare_logs", "vitamin_c")

    op.drop_index("ix_conflict_rules_code", table_name="conflict_rules")
    op.drop_column("conflict_rules", "evidence")
    op.drop_column("conflict_rules", "source")
    op.drop_column("conflict_rules", "category")
    op.drop_column("conflict_rules", "code")
