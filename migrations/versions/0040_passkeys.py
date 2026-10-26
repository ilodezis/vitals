"""passkeys — WebAuthn credentials for signing in without a password

One row per registered authenticator: its credential id (the only lookup a
sign-in performs, hence unique and indexed) and the public key that checks its
signatures. Nothing secret is stored.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "passkeys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", _JSON_TYPE, nullable=False),
        sa.Column("aaguid", sa.String(36), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_passkeys_credential_id", "passkeys", ["credential_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_passkeys_credential_id", table_name="passkeys")
    op.drop_table("passkeys")
