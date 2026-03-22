"""Data loading and filtering utilities."""

import json
import os
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# Default path - synced from prod via make sync-metrics
DEFAULT_DB_PATH = Path(os.environ.get("METRICS_DB", "data/metrics.duckdb"))

# Quick toggle presets (days back from max date)
QUICK_RANGES = {"7d": 7, "14d": 14, "30d": 30}


@st.cache_data(ttl=60)
def load_data(db_path: str) -> tuple[pd.DataFrame, str]:
    """Load all raw metrics events from DuckDB.

    Returns:
        Tuple of (dataframe, load_timestamp_string)
    """
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame(), ""

    conn = duckdb.connect(str(path), read_only=True)
    df = conn.execute("SELECT * FROM metrics_event ORDER BY timestamp").fetchdf()
    conn.close()

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        local_tz = datetime.now().astimezone().tzinfo
        df["local_time"] = df["timestamp"].dt.tz_convert(local_tz).dt.tz_localize(None)
        df["data"] = df["data"].apply(lambda x: json.loads(x) if isinstance(x, str) and x else {})

        # DuckDB auto_detect infers all-NULL columns as VARCHAR from CSV.
        # Coerce known numeric columns so downstream .sum()/.mean() work.
        numeric_cols = [
            "text_length",
            "queue_wait_ms",
            "worker_latency_ms",
            "total_latency_ms",
            "audio_duration_ms",
            "queue_depth",
            "retry_count",
            "duration_ms",
            "status_code",
            "page_idx",
            "block_idx",
            "prompt_token_count",
            "candidates_token_count",
            "thoughts_token_count",
            "cached_content_token_count",
            "total_token_count",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    loaded_at = datetime.now().strftime("%H:%M:%S")
    return df, loaded_at


@st.cache_data(ttl=60)
def load_daily(db_path: str) -> pd.DataFrame:
    """Load daily aggregate data from DuckDB.

    Returns daily aggregates with columns: bucket, event_type, model_slug,
    event_count, latency stats, cache stats, volume stats, unique_users.
    """
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()

    conn = duckdb.connect(str(path), read_only=True)
    try:
        df = conn.execute("SELECT * FROM metrics_daily ORDER BY bucket").fetchdf()
    except duckdb.CatalogException:
        return pd.DataFrame()
    finally:
        conn.close()

    if not df.empty:
        df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
        local_tz = datetime.now().astimezone().tzinfo
        df["local_date"] = df["bucket"].dt.tz_convert(local_tz).dt.tz_localize(None)

    return df


def get_db_info(db_path: Path) -> dict:
    """Get database file info."""
    if not db_path.exists():
        return {"exists": False}
    stat = db_path.stat()
    return {
        "exists": True,
        "size_kb": stat.st_size / 1024,
        "modified": datetime.fromtimestamp(stat.st_mtime),
    }


def filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """Filter dataframe to date range (inclusive)."""
    if df.empty:
        return df
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    mask = (df["local_time"] >= start_dt) & (df["local_time"] < end_dt)
    return df[mask]


def filter_by_models(df: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Filter dataframe to selected models. 'All' = no filter."""
    if df.empty or not models or "All" in models:
        return df
    mask = df["model_slug"].isin(models) | df["model_slug"].isna()
    return df[mask]


ANONYMOUS_PREFIX = "anon-"

USER_TYPE_ALL = "All"
USER_TYPE_GUEST = "Guest"
USER_TYPE_REGISTERED = "Registered"
USER_TYPES = [USER_TYPE_ALL, USER_TYPE_GUEST, USER_TYPE_REGISTERED]


def filter_by_user_type(df: pd.DataFrame, user_type: str) -> pd.DataFrame:
    """Filter by user type. Guest = anon-* user_ids, Registered = everything else."""
    if df.empty or user_type == USER_TYPE_ALL or "user_id" not in df.columns:
        return df
    is_guest = df["user_id"].fillna("").str.startswith(ANONYMOUS_PREFIX)
    if user_type == USER_TYPE_GUEST:
        return df[is_guest]
    return df[~is_guest]


def filter_data(df: pd.DataFrame, date_range: tuple, models: list[str], user_type: str = USER_TYPE_ALL) -> pd.DataFrame:
    """Apply all filters."""
    start, end = date_range
    filtered = filter_by_date_range(df, start, end)
    filtered = filter_by_models(filtered, models)
    filtered = filter_by_user_type(filtered, user_type)
    return filtered


# === Event-specific queries ===


def get_events(df: pd.DataFrame, event_type: str) -> pd.DataFrame:
    """Get events of a specific type."""
    return df[df["event_type"] == event_type]


def get_events_multi(df: pd.DataFrame, event_types: list[str]) -> pd.DataFrame:
    """Get events matching any of the given types."""
    return df[df["event_type"].isin(event_types)]


# === Gemini cost calculation ===

# Gemini 3 Flash Preview pricing
GEMINI_INPUT_COST_PER_M = 0.50
GEMINI_OUTPUT_COST_PER_M = 3.00


def calculate_gemini_cost(extraction_df: pd.DataFrame) -> float:
    """Calculate total Gemini API cost from page_extraction_complete events.

    Pass the pre-filtered DataFrame (already filtered to page_extraction_complete).
    """
    if extraction_df.empty:
        return 0.0
    prompt = extraction_df["prompt_token_count"].fillna(0).sum()
    output = (
        extraction_df["candidates_token_count"].fillna(0).sum() + extraction_df["thoughts_token_count"].fillna(0).sum()
    )
    return (prompt / 1e6) * GEMINI_INPUT_COST_PER_M + (output / 1e6) * GEMINI_OUTPUT_COST_PER_M


# === Aggregation helpers ===


def calculate_rate(hits: int, misses: int) -> float:
    """Calculate hit rate as percentage."""
    total = hits + misses
    return (hits / total * 100) if total > 0 else 0.0


def bin_by_time(df: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
    """Add a time bin column for aggregation."""
    if df.empty:
        return df
    df = df.copy()
    df["time_bin"] = df["local_time"].dt.floor(interval)
    return df


def get_time_range_info(df: pd.DataFrame) -> dict:
    """Get info about the time range in the data."""
    if df.empty:
        return {"min": None, "max": None, "span": None}
    min_time = df["local_time"].min()
    max_time = df["local_time"].max()
    return {
        "min": min_time,
        "max": max_time,
        "span": max_time - min_time,
    }
