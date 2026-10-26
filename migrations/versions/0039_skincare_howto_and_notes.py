"""skincare: how to apply each product, in what order, and notes on a day

* ``skincare_products.usage_morning`` / ``usage_evening`` — how to apply it in
  that slot, when it differs from the general ``usage_instructions``.
* ``skincare_products.step`` — its place in the order of application.
* ``skincare_notes`` — a comment on one slot of one day, shown above that slot's
  checklist in the app and in the Telegram reminder.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skincare_products", sa.Column("usage_morning", sa.Text(), nullable=True))
    op.add_column("skincare_products", sa.Column("usage_evening", sa.Text(), nullable=True))
    op.add_column("skincare_products", sa.Column("step", sa.Integer(), nullable=True))

    op.create_table(
        "skincare_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "slot", name="uq_skincare_notes_day_slot"),
    )
    op.create_index("ix_skincare_notes_date", "skincare_notes", ["date"])
    op.create_index("ix_skincare_notes_domain", "skincare_notes", ["domain"])
    op.create_index("ix_skincare_notes_domain_date", "skincare_notes", ["domain", "date"])


def downgrade() -> None:
    op.drop_index("ix_skincare_notes_domain_date", table_name="skincare_notes")
    op.drop_index("ix_skincare_notes_domain", table_name="skincare_notes")
    op.drop_index("ix_skincare_notes_date", table_name="skincare_notes")
    op.drop_table("skincare_notes")
    op.drop_column("skincare_products", "step")
    op.drop_column("skincare_products", "usage_evening")
    op.drop_column("skincare_products", "usage_morning")
