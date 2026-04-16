"""add voice plan, deactivate plus and max

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-04-07

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'voice' to plantier enum (requires autocommit for ALTER TYPE ADD VALUE)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE plantier ADD VALUE IF NOT EXISTS 'voice'")

    # Insert the Voice plan
    op.execute("""
        INSERT INTO plan (tier, name, server_kokoro_characters, premium_voice_characters, ocr_tokens,
                          trial_days, price_cents_monthly, price_cents_yearly, is_active)
        VALUES ('voice', 'Voice', NULL, 0, 0, 3, 300, 2700, true)
        ON CONFLICT (tier) DO NOTHING
    """)

    # Deactivate Plus and Max plans, zero out premium voice chars (Inworld removed)
    op.execute("UPDATE plan SET is_active = false, premium_voice_characters = 0 WHERE tier IN ('plus', 'max')")

    # Deactivate Inworld TTS models
    op.execute("UPDATE ttsmodel SET is_active = false WHERE slug LIKE 'inworld%'")


def downgrade() -> None:
    op.execute("UPDATE ttsmodel SET is_active = true WHERE slug LIKE 'inworld%'")
    op.execute("UPDATE plan SET is_active = true WHERE tier IN ('plus', 'max')")
    op.execute("DELETE FROM plan WHERE tier = 'voice'")
    # Cannot remove enum values in Postgres — 'voice' stays in the type
