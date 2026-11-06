"""passkey table

Revision ID: 8e3f1a6c2b47
Revises: d4b8c97a743c
Create Date: 2026-11-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8e3f1a6c2b47"
down_revision: str | None = "d4b8c97a743c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "passkey",
        sa.Column("credential_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("transports", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["useraccount.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("credential_id"),
    )
    op.create_index(op.f("ix_passkey_user_id"), "passkey", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_passkey_user_id"), table_name="passkey")
    op.drop_table("passkey")
