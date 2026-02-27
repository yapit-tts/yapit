"""add_audio_characters_to_document

Revision ID: 3b79fd79f78d
Revises: cbe49087b51f
Create Date: 2026-02-27 02:04:12.475766

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b79fd79f78d"
down_revision: Union[str, None] = "cbe49087b51f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document", sa.Column("audio_characters", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
        UPDATE document SET audio_characters = (
            SELECT COALESCE(SUM(LENGTH(text)), 0) FROM block WHERE block.document_id = document.id
        )
    """)
    op.alter_column("document", "audio_characters", server_default=None)


def downgrade() -> None:
    op.drop_column("document", "audio_characters")
