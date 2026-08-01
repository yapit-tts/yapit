"""invalidate stale non-english kokoro audio

Before the per-language G2P fix (#87), all Kokoro voices synthesized through the
English pipeline, so cached audio for non-English voices is English-phonemized
garbage. The audio cache is keyed by sha256(text|model|voice|parameters) with no
TTL, so that audio would be served forever. Adding a marker to the parameters of
non-English voices changes every affected hash: old entries become orphans (the
LRU cache evicts them) and the next request re-synthesizes correctly. English
(a/b) voices are untouched — their cached audio is fine.

The marker records a fact ("this voice uses its native G2P frontend"), but
nothing reads it; its purpose is the hash change. seed.py includes it for fresh
databases.

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-08-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE voice SET parameters = parameters || '{"g2p": "native"}'::jsonb
        WHERE model_id IN (SELECT id FROM ttsmodel WHERE slug = 'kokoro')
          AND left(slug, 1) NOT IN ('a', 'b')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE voice SET parameters = parameters - 'g2p'
        WHERE model_id IN (SELECT id FROM ttsmodel WHERE slug = 'kokoro')
          AND left(slug, 1) NOT IN ('a', 'b')
    """)
