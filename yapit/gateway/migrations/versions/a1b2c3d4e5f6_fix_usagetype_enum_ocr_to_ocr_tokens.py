"""fix usagetype enum: ocr -> ocr_tokens

Revision ID: a1b2c3d4e5f6
Revises: 1a82735db431
Create Date: 2026-01-24 12:00:00.000000

The token billing refactor (df88ca3f6320) renamed columns from ocr_pages to ocr_tokens
but didn't update the PostgreSQL usagetype enum. The Python UsageType enum uses
ocr_tokens, causing "invalid input value for enum usagetype: ocr_tokens" errors.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "1a82735db431"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE usagetype ADD VALUE IF NOT EXISTS 'ocr_tokens'")
    op.execute("UPDATE usagelog SET type = 'ocr_tokens' WHERE type = 'ocr'")


def downgrade() -> None:
    pass
