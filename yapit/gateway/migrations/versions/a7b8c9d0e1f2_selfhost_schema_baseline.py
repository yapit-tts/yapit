"""selfhost schema baseline

Self-hosting originally used SQLAlchemy's create_all() instead of Alembic.
create_all() creates missing tables on first run but never alters existing ones,
so self-hosters who upgraded to newer code never got new columns — the app just
crashed (e.g. "column userpreferences.extraction_prompt does not exist").

The fix: self-hosting now uses Alembic like production. This one-time migration
bridges the gap for existing self-host databases by ensuring the schema matches
the current models using idempotent SQL (IF NOT EXISTS / IF EXISTS everywhere).
On production and fresh installs this is a no-op — everything already exists.

Revision ID: a7b8c9d0e1f2
Revises: 86c4c0dd6eeb
Create Date: 2026-04-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "86c4c0dd6eeb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # fmt: off
    op.execute("""
    -- ================================================================
    -- Tables added after initial schema
    -- ================================================================

    CREATE TABLE IF NOT EXISTS plan (
        id SERIAL PRIMARY KEY,
        tier VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        server_kokoro_characters INTEGER,
        premium_voice_characters INTEGER,
        ocr_tokens INTEGER,
        stripe_price_id_monthly VARCHAR,
        stripe_price_id_yearly VARCHAR,
        trial_days INTEGER NOT NULL DEFAULT 0,
        price_cents_monthly INTEGER NOT NULL DEFAULT 0,
        price_cents_yearly INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ix_plan_tier ON plan (tier);

    CREATE TABLE IF NOT EXISTS usagelog (
        id UUID PRIMARY KEY,
        user_id VARCHAR NOT NULL,
        type VARCHAR NOT NULL,
        amount INTEGER NOT NULL,
        description VARCHAR,
        details JSONB,
        reference_id VARCHAR,
        event_id VARCHAR,
        created TIMESTAMP WITH TIME ZONE
    );
    CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usagelog (created);
    CREATE INDEX IF NOT EXISTS idx_usage_log_user_created ON usagelog (user_id, created);
    CREATE INDEX IF NOT EXISTS ix_usagelog_reference_id ON usagelog (reference_id);
    CREATE INDEX IF NOT EXISTS ix_usagelog_user_id ON usagelog (user_id);

    CREATE TABLE IF NOT EXISTS usageperiod (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR NOT NULL,
        plan_id INTEGER REFERENCES plan(id),
        period_start TIMESTAMP WITH TIME ZONE NOT NULL,
        period_end TIMESTAMP WITH TIME ZONE NOT NULL,
        server_kokoro_characters INTEGER NOT NULL DEFAULT 0,
        premium_voice_characters INTEGER NOT NULL DEFAULT 0,
        ocr_tokens INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_usage_period_user_period ON usageperiod (user_id, period_start);
    CREATE INDEX IF NOT EXISTS ix_usageperiod_user_id ON usageperiod (user_id);

    CREATE TABLE IF NOT EXISTS usersubscription (
        user_id VARCHAR PRIMARY KEY,
        plan_id INTEGER NOT NULL REFERENCES plan(id),
        status VARCHAR NOT NULL,
        stripe_customer_id VARCHAR,
        stripe_subscription_id VARCHAR,
        current_period_start TIMESTAMP WITH TIME ZONE NOT NULL,
        current_period_end TIMESTAMP WITH TIME ZONE NOT NULL,
        cancel_at_period_end BOOLEAN NOT NULL DEFAULT false,
        cancel_at TIMESTAMP WITH TIME ZONE,
        canceled_at TIMESTAMP WITH TIME ZONE,
        highest_tier_subscribed VARCHAR,
        ever_paid BOOLEAN NOT NULL DEFAULT false,
        rollover_tokens INTEGER NOT NULL DEFAULT 0,
        rollover_voice_chars INTEGER NOT NULL DEFAULT 0,
        last_rollover_invoice_id VARCHAR,
        purchased_tokens INTEGER NOT NULL DEFAULT 0,
        purchased_voice_chars INTEGER NOT NULL DEFAULT 0,
        created TIMESTAMP WITH TIME ZONE,
        updated TIMESTAMP WITH TIME ZONE
    );
    CREATE INDEX IF NOT EXISTS ix_usersubscription_stripe_customer_id ON usersubscription (stripe_customer_id);
    CREATE UNIQUE INDEX IF NOT EXISTS ix_usersubscription_stripe_subscription_id ON usersubscription (stripe_subscription_id);

    CREATE TABLE IF NOT EXISTS userpreferences (
        user_id VARCHAR PRIMARY KEY,
        pinned_voices JSONB NOT NULL DEFAULT '[]'::jsonb,
        auto_import_shared_documents BOOLEAN NOT NULL DEFAULT false,
        default_documents_public BOOLEAN NOT NULL DEFAULT false,
        extraction_prompt TEXT,
        created TIMESTAMP WITH TIME ZONE,
        updated TIMESTAMP WITH TIME ZONE
    );

    CREATE TABLE IF NOT EXISTS uservoicestats (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR NOT NULL,
        voice_slug VARCHAR NOT NULL,
        model_slug VARCHAR NOT NULL,
        month DATE NOT NULL,
        total_characters INTEGER NOT NULL DEFAULT 0,
        total_duration_ms INTEGER NOT NULL DEFAULT 0,
        synth_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS ix_uservoicestats_user_id ON uservoicestats (user_id);

    -- ================================================================
    -- Columns added to existing tables
    -- ================================================================

    -- document
    ALTER TABLE document ADD COLUMN IF NOT EXISTS last_block_idx INTEGER;
    ALTER TABLE document ADD COLUMN IF NOT EXISTS last_played_at TIMESTAMP WITH TIME ZONE;
    ALTER TABLE document ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE document ADD COLUMN IF NOT EXISTS content_hash VARCHAR;
    ALTER TABLE document ADD COLUMN IF NOT EXISTS audio_characters INTEGER NOT NULL DEFAULT 0;

    -- ttsmodel
    ALTER TABLE ttsmodel ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
    ALTER TABLE ttsmodel ADD COLUMN IF NOT EXISTS usage_multiplier FLOAT NOT NULL DEFAULT 1.0;

    -- voice
    ALTER TABLE voice ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

    -- documentprocessor (may not exist on newer create_all installs, that's fine)
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'documentprocessor') THEN
            ALTER TABLE documentprocessor ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
        END IF;
    END $$;

    -- userpreferences (columns, table created above)
    ALTER TABLE userpreferences ADD COLUMN IF NOT EXISTS auto_import_shared_documents BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE userpreferences ADD COLUMN IF NOT EXISTS default_documents_public BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE userpreferences ADD COLUMN IF NOT EXISTS extraction_prompt TEXT;

    -- usagelog
    ALTER TABLE usagelog ADD COLUMN IF NOT EXISTS event_id VARCHAR;

    -- usageperiod
    ALTER TABLE usageperiod ADD COLUMN IF NOT EXISTS ocr_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usageperiod ADD COLUMN IF NOT EXISTS plan_id INTEGER REFERENCES plan(id);

    -- plan
    ALTER TABLE plan ADD COLUMN IF NOT EXISTS ocr_tokens INTEGER;

    -- usersubscription
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS highest_tier_subscribed VARCHAR;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS rollover_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS rollover_voice_chars INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS purchased_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS purchased_voice_chars INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS cancel_at TIMESTAMP WITH TIME ZONE;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS ever_paid BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE usersubscription ADD COLUMN IF NOT EXISTS last_rollover_invoice_id VARCHAR;

    -- ================================================================
    -- Columns dropped (cleanup for old create_all installs)
    -- ================================================================

    ALTER TABLE document DROP COLUMN IF EXISTS filtered_text;
    ALTER TABLE ttsmodel DROP COLUMN IF EXISTS credits_per_sec;
    ALTER TABLE ttsmodel DROP COLUMN IF EXISTS native_codec;
    ALTER TABLE ttsmodel DROP COLUMN IF EXISTS channels;
    ALTER TABLE ttsmodel DROP COLUMN IF EXISTS sample_rate;
    ALTER TABLE ttsmodel DROP COLUMN IF EXISTS sample_width;
    ALTER TABLE blockvariant DROP COLUMN IF EXISTS block_id;
    ALTER TABLE blockvariant DROP COLUMN IF EXISTS cache_ref;
    ALTER TABLE usersubscription DROP COLUMN IF EXISTS grace_tier;
    ALTER TABLE usersubscription DROP COLUMN IF EXISTS grace_until;
    ALTER TABLE usersubscription DROP COLUMN IF EXISTS previous_plan_id;

    -- plan/usageperiod: drop old columns if they exist
    ALTER TABLE plan DROP COLUMN IF EXISTS ocr_pages;
    ALTER TABLE usageperiod DROP COLUMN IF EXISTS ocr_pages;

    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'documentprocessor') THEN
            ALTER TABLE documentprocessor DROP COLUMN IF EXISTS credits_per_page;
        END IF;
    END $$;

    -- ================================================================
    -- Tables dropped
    -- ================================================================

    DROP TABLE IF EXISTS block;
    DROP TABLE IF EXISTS filter;

    -- ================================================================
    -- Indexes and constraints
    -- ================================================================

    CREATE INDEX IF NOT EXISTS ix_document_content_hash ON document (content_hash);
    CREATE INDEX IF NOT EXISTS idx_document_user_created ON document (user_id, created);
    CREATE INDEX IF NOT EXISTS ix_ttsmodel_is_active ON ttsmodel (is_active);
    CREATE INDEX IF NOT EXISTS ix_voice_is_active ON voice (is_active);

    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'documentprocessor') THEN
            CREATE INDEX IF NOT EXISTS ix_documentprocessor_is_active ON documentprocessor (is_active);
        END IF;
    END $$;

    -- Unique constraints (no IF NOT EXISTS syntax, so check first)
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_usage_period_user_period') THEN
            ALTER TABLE usageperiod ADD CONSTRAINT uq_usage_period_user_period UNIQUE (user_id, period_start);
        END IF;
    END $$;

    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usagelog_event_id_key') THEN
            ALTER TABLE usagelog ADD CONSTRAINT usagelog_event_id_key UNIQUE (event_id);
        END IF;
    END $$;

    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_voice_stats') THEN
            ALTER TABLE uservoicestats ADD CONSTRAINT uq_user_voice_stats UNIQUE (user_id, voice_slug, model_slug, month);
        END IF;
    END $$;

    -- Enum: ensure ocr_tokens value exists
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'usagetype') THEN
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'ocr_tokens' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'usagetype')) THEN
                ALTER TYPE usagetype ADD VALUE 'ocr_tokens';
            END IF;
        END IF;
    END $$;
    """)
    # fmt: on


def downgrade() -> None:
    pass
