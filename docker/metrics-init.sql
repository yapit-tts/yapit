-- TimescaleDB initialization for metrics
-- This runs once when the container is first created

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Main metrics table
CREATE TABLE IF NOT EXISTS metrics_event (
    id BIGSERIAL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,

    -- Synthesis/detection fields
    model_slug TEXT,
    voice_slug TEXT,
    variant_hash TEXT,
    text_length INTEGER,
    queue_wait_ms INTEGER,
    worker_latency_ms INTEGER,
    total_latency_ms INTEGER,
    audio_duration_ms INTEGER,
    cache_hit BOOLEAN,
    queue_depth INTEGER,

    -- Worker/queue fields
    worker_id TEXT,
    queue_type TEXT,  -- 'tts' or 'detection'
    retry_count INTEGER,

    -- LLM/extraction fields
    processor_slug TEXT,
    page_idx INTEGER,
    prompt_token_count INTEGER,
    candidates_token_count INTEGER,
    thoughts_token_count INTEGER,
    total_token_count INTEGER,

    -- Request fields
    endpoint TEXT,
    method TEXT,
    status_code INTEGER,
    duration_ms INTEGER,

    -- Context
    user_id TEXT,
    document_id TEXT,
    request_id TEXT,
    block_idx INTEGER,

    -- Flexible data (tracebacks, extra context)
    data JSONB
);

-- Convert to hypertable (partitioned by time, 1 day chunks)
SELECT create_hypertable('metrics_event', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_metrics_event_type ON metrics_event(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_model ON metrics_event(model_slug, timestamp DESC) WHERE model_slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_metrics_user ON metrics_event(user_id, timestamp DESC) WHERE user_id IS NOT NULL;

-- Compression policy: compress chunks older than 7 days
ALTER TABLE metrics_event SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'event_type, model_slug'
);
SELECT add_compression_policy('metrics_event', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy: drop raw data older than 30 days
SELECT add_retention_policy('metrics_event', INTERVAL '30 days', if_not_exists => TRUE);

-- ============================================================================
-- Continuous Aggregates
-- ============================================================================

-- Hourly aggregates (kept for 1 year)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    event_type,
    model_slug,
    COUNT(*) AS event_count,

    -- Latency stats (for synthesis events)
    AVG(worker_latency_ms) AS avg_worker_latency_ms,
    AVG(total_latency_ms) AS avg_total_latency_ms,
    AVG(queue_wait_ms) AS avg_queue_wait_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_total_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_total_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_latency_ms) AS p99_total_latency_ms,

    -- Queue stats
    AVG(queue_depth) AS avg_queue_depth,
    MAX(queue_depth) AS max_queue_depth,

    -- Cache stats
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) AS cache_misses,

    -- Synthesis stats
    SUM(text_length) AS total_chars,
    SUM(audio_duration_ms) AS total_audio_ms,

    -- Unique users (approximation)
    COUNT(DISTINCT user_id) AS unique_users
FROM metrics_event
GROUP BY bucket, event_type, model_slug
WITH NO DATA;

-- Refresh policy for hourly aggregates
SELECT add_continuous_aggregate_policy('metrics_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- Retention for hourly aggregates: 1 year
SELECT add_retention_policy('metrics_hourly', INTERVAL '1 year', if_not_exists => TRUE);

-- Daily aggregates (kept forever)
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS bucket,
    event_type,
    model_slug,
    COUNT(*) AS event_count,

    -- Latency stats
    AVG(worker_latency_ms) AS avg_worker_latency_ms,
    AVG(total_latency_ms) AS avg_total_latency_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_total_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_total_latency_ms,

    -- Cache stats
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) AS cache_misses,

    -- Volume stats
    SUM(text_length) AS total_chars,
    SUM(audio_duration_ms) AS total_audio_ms,

    -- Unique users
    COUNT(DISTINCT user_id) AS unique_users
FROM metrics_event
GROUP BY bucket, event_type, model_slug
WITH NO DATA;

-- Refresh policy for daily aggregates
SELECT add_continuous_aggregate_policy('metrics_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- No retention policy for daily = kept forever
