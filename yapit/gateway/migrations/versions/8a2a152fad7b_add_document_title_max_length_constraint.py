"""add document title max_length constraint

Revision ID: 8a2a152fad7b
Revises: a44631da648a
Create Date: 2026-01-07 08:11:23.984456

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a2a152fad7b"
down_revision: Union[str, None] = "a44631da648a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("document", "title", existing_type=sa.TEXT(), type_=sa.String(length=500), existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("document", "title", existing_type=sa.String(length=500), type_=sa.TEXT(), existing_nullable=True)
