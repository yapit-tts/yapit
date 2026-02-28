"""drop_block_table

Revision ID: a5b9e7f3d359
Revises: 3b79fd79f78d
Create Date: 2026-02-28 11:44:27.739667

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5b9e7f3d359"
down_revision: Union[str, None] = "3b79fd79f78d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("block")


def downgrade() -> None:
    op.create_table(
        "block",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
