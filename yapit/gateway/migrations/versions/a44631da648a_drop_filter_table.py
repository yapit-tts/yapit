"""drop filter table

Revision ID: a44631da648a
Revises: 01e63e9176ff
Create Date: 2026-01-06 19:28:50.825210

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a44631da648a"
down_revision: Union[str, None] = "01e63e9176ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused filter table."""
    op.drop_index(op.f("ix_filter_user_id"), table_name="filter")
    op.drop_index(op.f("ix_filter_name"), table_name="filter")
    op.drop_table("filter")


def downgrade() -> None:
    """Recreate filter table."""
    op.create_table(
        "filter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_filter_name"), "filter", ["name"], unique=False)
    op.create_index(op.f("ix_filter_user_id"), "filter", ["user_id"], unique=False)
