-- Add processor_slug to GROUP BY and duration_ms stats to continuous aggregates.
--
-- Enables per-processor trending for document extraction metrics and
-- duration percentiles for any event using the duration_ms column.
--
-- TimescaleDB doesn't support ALTER on continuous aggregates.
-- Must DROP + CREATE. Existing materialized data is lost — new data
-- accumulates going forward from the refresh policy.
--
-- Apply: ssh prod 'docker exec $(docker ps -qf name=metrics-db) psql -U metrics -d metrics' < docker/metrics-migrations/003_add_processor_slug_duration_to_aggregates.sql

-- ============================================================================
-- Hourly aggregates
-- ============================================================================

SELECT remove_continuous_aggregate_policy('metrics_hourly', if_exists => TRUE);
SELECT remove_retention_policy('metrics_hourly', if_exists => TRUE);

DROP MATERIALIZED VIEW IF EXISTS metrics_hourly CASCADE;

CREATE MATERIALIZED VIEW metrics_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    event_type,
    model_slug,
    processor_slug,
    COUNT(*) AS event_count,

    -- Latency stats
    AVG(worker_latency_ms) AS avg_worker_latency_ms,
    AVG(total_latency_ms) AS avg_total_latency_ms,
    AVG(queue_wait_ms) AS avg_queue_wait_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_total_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_total_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_latency_ms) AS p99_total_latency_ms,

    -- Duration stats (document extraction, URL fetch, webhooks, etc.)
    AVG(duration_ms) AS avg_duration_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms,

    -- Queue stats
    AVG(queue_depth) AS avg_queue_depth,
    MAX(queue_depth) AS max_queue_depth,

    -- Cache stats
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) AS cache_misses,

    -- Synthesis stats
    SUM(text_length) AS total_chars,
    SUM(audio_duration_ms) AS total_audio_ms,

    -- Token stats (for extraction cost tracking)
    SUM(prompt_token_count) AS total_prompt_tokens,
    SUM(candidates_token_count) AS total_candidates_tokens,
    SUM(thoughts_token_count) AS total_thoughts_tokens,
    SUM(cached_content_token_count) AS total_cached_tokens,
    SUM(total_token_count) AS total_all_tokens,

    -- Unique users
    COUNT(DISTINCT user_id) AS unique_users
FROM metrics_event
GROUP BY bucket, event_type, model_slug, processor_slug
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_retention_policy('metrics_hourly', INTERVAL '1 year', if_not_exists => TRUE);

-- ============================================================================
-- Daily aggregates
-- ============================================================================

SELECT remove_continuous_aggregate_policy('metrics_daily', if_exists => TRUE);

DROP MATERIALIZED VIEW IF EXISTS metrics_daily CASCADE;

CREATE MATERIALIZED VIEW metrics_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS bucket,
    event_type,
    model_slug,
    processor_slug,
    COUNT(*) AS event_count,

    -- Latency stats
    AVG(worker_latency_ms) AS avg_worker_latency_ms,
    AVG(total_latency_ms) AS avg_total_latency_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_total_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_total_latency_ms,

    -- Duration stats
    AVG(duration_ms) AS avg_duration_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms,

    -- Cache stats
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) AS cache_misses,

    -- Volume stats
    SUM(text_length) AS total_chars,
    SUM(audio_duration_ms) AS total_audio_ms,

    -- Token stats (for extraction cost tracking)
    SUM(prompt_token_count) AS total_prompt_tokens,
    SUM(candidates_token_count) AS total_candidates_tokens,
    SUM(thoughts_token_count) AS total_thoughts_tokens,
    SUM(cached_content_token_count) AS total_cached_tokens,
    SUM(total_token_count) AS total_all_tokens,

    -- Unique users
    COUNT(DISTINCT user_id) AS unique_users
FROM metrics_event
GROUP BY bucket, event_type, model_slug, processor_slug
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- No retention policy for daily = kept forever
