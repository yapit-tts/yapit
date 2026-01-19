"""Data loading and filtering utilities."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# Default path - synced from prod via make sync-metrics
DEFAULT_DB_PATH = Path(os.environ.get("METRICS_DB", "gateway-data/metrics.duckdb"))


@st.cache_data(ttl=60)
def load_data(db_path: str) -> tuple[pd.DataFrame, str]:
    """Load all metrics data from DuckDB.

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
        # Convert to local timezone for display
        local_tz = datetime.now().astimezone().tzinfo
        df["local_time"] = df["timestamp"].dt.tz_convert(local_tz).dt.tz_localize(None)
        # Parse JSON data column
        df["data"] = df["data"].apply(lambda x: json.loads(x) if isinstance(x, str) and x else {})

    loaded_at = datetime.now().strftime("%H:%M:%S")
    return df, loaded_at


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
    # Include rows with matching model_slug OR null model_slug (non-model events)
    mask = df["model_slug"].isin(models) | df["model_slug"].isna()
    return df[mask]


def filter_data(df: pd.DataFrame, date_range: tuple, models: list[str]) -> pd.DataFrame:
    """Apply all filters."""
    start, end = date_range
    filtered = filter_by_date_range(df, start, end)
    filtered = filter_by_models(filtered, models)
    return filtered


# === Event-specific queries ===


def get_events(df: pd.DataFrame, event_type: str) -> pd.DataFrame:
    """Get events of a specific type."""
    return df[df["event_type"] == event_type]


def get_events_multi(df: pd.DataFrame, event_types: list[str]) -> pd.DataFrame:
    """Get events matching any of the given types."""
    return df[df["event_type"].isin(event_types)]


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


def get_comparison_periods(df: pd.DataFrame, current_start, current_end):
    """Get data for comparison periods (yesterday, last week)."""
    current_span = current_end - current_start

    # Yesterday (same duration, shifted back)
    yesterday_end = current_start
    yesterday_start = yesterday_end - current_span - timedelta(days=1)

    # Last week (same duration, shifted back 7 days)
    last_week_end = current_start - timedelta(days=6)
    last_week_start = last_week_end - current_span - timedelta(days=1)

    return {
        "yesterday": filter_by_date_range(df, yesterday_start, yesterday_end),
        "last_week": filter_by_date_range(df, last_week_start, last_week_end),
    }
