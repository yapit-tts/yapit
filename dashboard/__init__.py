"""Yapit Metrics Dashboard.

A dark-mode Streamlit dashboard for monitoring TTS, detection, extraction,
and overall system performance.

Run via: make dashboard
"""

import subprocess
from datetime import timedelta
from pathlib import Path

import streamlit as st

from dashboard.data import DEFAULT_DB_PATH, filter_data, get_db_info, get_time_range_info, load_data
from dashboard.tabs import (
    render_detection,
    render_extraction,
    render_overview,
    render_reliability,
    render_tts,
    render_usage,
)
from dashboard.theme import inject_css


def main():
    """Main dashboard entrypoint."""
    st.set_page_config(
        page_title="Yapit Metrics",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_css()

    st.title("📊 Yapit Metrics Dashboard")

    # Sidebar: data loading and filters
    with st.sidebar:
        st.markdown("### Data")

        db_path = Path(DEFAULT_DB_PATH)
        db_info = get_db_info(db_path)

        if not db_info["exists"]:
            st.error(f"Database not found: {db_path}")
            st.info("Run `make sync-metrics` to sync from prod")
            return

        st.caption(f"Size: {db_info['size_kb']:.1f} KB")
        st.caption(f"Modified: {db_info['modified'].strftime('%Y-%m-%d %H:%M')}")

        # Sync from prod button
        if st.button("🔄 Sync from Prod", use_container_width=True):
            with st.spinner("Syncing metrics from prod..."):
                result = subprocess.run(["make", "sync-metrics"], capture_output=True, text=True)
                if result.returncode != 0:
                    st.error(f"Sync failed: {result.stderr}")
                else:
                    st.cache_data.clear()
                    st.rerun()

        df, loaded_at = load_data(str(db_path))
        st.caption(f"Loaded: {loaded_at}")

        if df.empty:
            st.warning("Database is empty")
            return

        st.divider()
        st.markdown("### Filters")

        # Date range
        time_info = get_time_range_info(df)
        min_date = time_info["min"].date()
        max_date = time_info["max"].date()
        default_start = max(min_date, max_date - timedelta(days=7))

        date_range = st.date_input(
            "Date Range",
            value=(default_start, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        # Handle single date selection
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date = end_date = date_range[0] if isinstance(date_range, tuple) else date_range

        # Model filter
        models = ["All"] + sorted(df["model_slug"].dropna().unique().tolist())
        selected_models = st.multiselect("Models", models, default=["All"])

        st.divider()

        # Quick stats
        filtered = filter_data(df, (start_date, end_date), selected_models)
        st.caption(f"**{len(filtered):,}** events in range")
        st.caption(f"Filter: {start_date} to {end_date}")
        if not filtered.empty:
            span = filtered["local_time"].max() - filtered["local_time"].min()
            st.caption(f"Span: {span}")

    # Filter data
    filtered = filter_data(df, (start_date, end_date), selected_models)

    if filtered.empty:
        st.warning("No data for selected filters")
        return

    # Tabs
    tabs = st.tabs(["Overview", "TTS", "Detection", "Extraction", "Reliability", "Usage"])

    with tabs[0]:
        render_overview(filtered)

    with tabs[1]:
        render_tts(filtered)

    with tabs[2]:
        render_detection(filtered)

    with tabs[3]:
        render_extraction(filtered)

    with tabs[4]:
        render_reliability(filtered)

    with tabs[5]:
        render_usage(filtered)


if __name__ == "__main__":
    main()
