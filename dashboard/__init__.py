"""Yapit Metrics Dashboard.

A dark-mode Streamlit dashboard for monitoring TTS, detection, extraction,
and overall system performance.

Run via: make dashboard
"""

import subprocess
from datetime import timedelta
from pathlib import Path

import streamlit as st

from dashboard.data import (
    DEFAULT_DB_PATH,
    QUICK_RANGES,
    USER_TYPE_ALL,
    USER_TYPES,
    filter_data,
    get_db_info,
    get_time_range_info,
    load_daily,
    load_data,
)
from dashboard.tabs import (
    render_documents,
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

    st.title("Yapit Control Center")

    # Sidebar: data loading and filters
    with st.sidebar:
        st.markdown("### Data")

        db_path = Path(DEFAULT_DB_PATH)
        db_info = get_db_info(db_path)

        if not db_info["exists"]:
            st.error(f"Database not found: {db_path}")
            st.info("Run `make sync-metrics` to sync from prod")
            return

        st.caption(f"Size: {db_info['size_kb']:.1f} KB | Modified: {db_info['modified'].strftime('%Y-%m-%d %H:%M')}")

        if st.button("Sync from Prod", width="stretch"):
            with st.spinner("Syncing metrics from prod..."):
                result = subprocess.run(["make", "sync-metrics"], capture_output=True, text=True)
                if result.returncode != 0:
                    st.error(f"Sync failed: {result.stderr}")
                else:
                    st.cache_data.clear()
                    st.rerun()

        df, loaded_at = load_data(str(db_path))
        daily_df = load_daily(str(db_path))
        st.caption(f"Loaded: {loaded_at}")

        if df.empty:
            st.warning("Database is empty")
            return

        st.divider()
        st.markdown("### Time Range")

        time_info = get_time_range_info(df)
        min_date = time_info["min"].date()
        max_date = time_info["max"].date()

        # Quick toggles
        range_options = list(QUICK_RANGES.keys())
        selected_range = st.radio("Quick select", range_options, index=0, horizontal=True)
        days_back = QUICK_RANGES[selected_range]
        start_date = max(min_date, max_date - timedelta(days=days_back))
        end_date = max_date

        # Custom range override (expandable)
        with st.expander("Custom range"):
            date_range = st.date_input(
                "Date Range",
                value=(start_date, end_date),
                min_value=min_date,
                max_value=max_date,
            )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date, end_date = date_range
            elif isinstance(date_range, tuple):
                start_date = end_date = date_range[0]
            else:
                start_date = end_date = date_range

        # Filters
        st.divider()
        st.markdown("### Filters")

        selected_user_type = st.radio("User Type", USER_TYPES, index=0, horizontal=True)

        models = ["All"] + sorted(df["model_slug"].dropna().unique().tolist())
        selected_models = st.multiselect("Models", models, default=["All"])

        st.divider()

        filtered = filter_data(df, (start_date, end_date), selected_models, selected_user_type)
        st.caption(f"**{len(filtered):,}** events in range")
        st.caption(f"{start_date} to {end_date}")
        if selected_user_type != USER_TYPE_ALL:
            st.caption(f"Showing: **{selected_user_type}** users only")
        if not filtered.empty:
            span = filtered["local_time"].max() - filtered["local_time"].min()
            st.caption(f"Span: {span}")

    if filtered.empty:
        st.warning("No data for selected filters")
        return

    # Tabs
    tabs = st.tabs(["Overview", "TTS", "Documents", "Reliability", "Usage"])

    with tabs[0]:
        render_overview(filtered, daily_df)

    with tabs[1]:
        render_tts(filtered)

    with tabs[2]:
        render_documents(filtered)

    with tabs[3]:
        render_reliability(filtered)

    with tabs[4]:
        render_usage(filtered)


if __name__ == "__main__":
    main()
