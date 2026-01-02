"""add grace period fields to usersubscription

Revision ID: 1bfa956c76b4
Revises: 18ecbc440912
Create Date: 2026-01-02 01:15:43.526114

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1bfa956c76b4"
down_revision: Union[str, None] = "18ecbc440912"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "usersubscription",
        sa.Column("grace_tier", sa.Enum("free", "basic", "plus", "max", name="plantier"), nullable=True),
    )
    op.add_column("usersubscription", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("usersubscription", "grace_until")
    op.drop_column("usersubscription", "grace_tier")
