"""skincare: done-tracking per product and slot, the face photo diary

* ``skincare_checks`` — one row per product done in a slot (morning / evening) on
  a day. Written by a tap in the app or under the Telegram reminder; the day's
  ``skincare_logs`` flags are derived from it from now on.
* ``skincare_products.active_flag`` — which conflict-engine flag a product sets
  when it is ticked. Backfilled from the free-text type / name / ingredient with
  the same keywords the catalog was seeded with; anything unrecognised stays
  null (tracked, never conflicting) and can be set in the product form.
* ``skincare_photos`` — the face photo diary, shaped like ``progress_photos``.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# First match wins, so the specific actives come before the catch-all cream.
_FLAG_KEYWORDS = (
    ("retinoid", ("ретино", "адапален", "третиноин", "дифферин", "retino", "adapalene", "tretinoin")),
    ("azelaic", ("азела", "azela")),
    ("benzoyl_peroxide", ("бензоил", "benzoyl")),
    ("peel", ("пилинг", "aha", "bha", "peel")),
    ("vitamin_c", ("витамин c", "витамин с", "аскорб", "vitamin c", "ascorb")),
    ("niacinamide_spf", ("ниацинамид", "spf", "niacinamide")),
    ("moisturizer", ("увлажн", "крем", "moistur", "cream")),
)


def guess_flag(*texts: str | None) -> str | None:
    haystack = " ".join(t for t in texts if t).lower()
    for flag, words in _FLAG_KEYWORDS:
        if any(w in haystack for w in words):
            return flag
    return None


def upgrade() -> None:
    op.add_column(
        "skincare_products", sa.Column("active_flag", sa.String(32), nullable=True)
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, name, type, active_ingredient FROM skincare_products")
    ).fetchall()
    for row in rows:
        flag = guess_flag(row.type, row.name, row.active_ingredient)
        if flag is not None:
            conn.execute(
                sa.text("UPDATE skincare_products SET active_flag = :flag WHERE id = :id"),
                {"flag": flag, "id": row.id},
            )

    op.create_table(
        "skincare_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("product_name", sa.String(128), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("active_flag", sa.String(32), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["skincare_products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "date", "product_id", "slot", name="uq_skincare_checks_day_product_slot"
        ),
    )
    op.create_index("ix_skincare_checks_date", "skincare_checks", ["date"])
    op.create_index("ix_skincare_checks_domain", "skincare_checks", ["domain"])
    op.create_index("ix_skincare_checks_domain_date", "skincare_checks", ["domain", "date"])
    op.create_index("ix_skincare_checks_product_id", "skincare_checks", ["product_id"])

    op.create_table(
        "skincare_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("file_key", sa.String(512), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skincare_photos_date", "skincare_photos", ["date"])
    op.create_index("ix_skincare_photos_domain", "skincare_photos", ["domain"])
    op.create_index("ix_skincare_photos_domain_date", "skincare_photos", ["domain", "date"])


def downgrade() -> None:
    op.drop_index("ix_skincare_photos_domain_date", table_name="skincare_photos")
    op.drop_index("ix_skincare_photos_domain", table_name="skincare_photos")
    op.drop_index("ix_skincare_photos_date", table_name="skincare_photos")
    op.drop_table("skincare_photos")
    op.drop_index("ix_skincare_checks_product_id", table_name="skincare_checks")
    op.drop_index("ix_skincare_checks_domain_date", table_name="skincare_checks")
    op.drop_index("ix_skincare_checks_domain", table_name="skincare_checks")
    op.drop_index("ix_skincare_checks_date", table_name="skincare_checks")
    op.drop_table("skincare_checks")
    op.drop_column("skincare_products", "active_flag")
