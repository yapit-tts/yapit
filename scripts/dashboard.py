#!/usr/bin/env python3
"""Metrics dashboard for Yapit TTS.

Usage:
    make dashboard        # sync from prod + open
    make dashboard-local  # use local metrics.db
"""

import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Config
LOCAL_DB = Path("metrics/metrics.db")
PROD_HOST = "root@78.46.242.1"
PROD_DB_PATH = "/data/metrics/metrics.db"

# Color palette - warm, readable
COLORS = {
    "primary": "#2d3436",  # dark gray
    "secondary": "#636e72",  # medium gray
    "accent": "#00b894",  # teal green
    "accent2": "#fdcb6e",  # warm yellow
    "accent3": "#e17055",  # coral
    "accent4": "#74b9ff",  # light blue
    "success": "#00b894",
    "warning": "#fdcb6e",
    "error": "#d63031",
    "local": "#00b894",  # green for local
    "overflow": "#e17055",  # coral for overflow
}

MODEL_COLORS = {
    "kokoro": "#00b894",
    "kokoro-cpu": "#00b894",
    "inworld-max": "#74b9ff",
    "higgs": "#e17055",
}


def get_model_color(model: str) -> str:
    for key, color in MODEL_COLORS.items():
        if key in model.lower():
            return color
    return COLORS["secondary"]


def sync_from_prod() -> tuple[bool, str]:
    """Sync metrics.db from production."""
    LOCAL_DB.parent.mkdir(exist_ok=True)
    tmp_path = f"/tmp/metrics-{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

    try:
        cmd = f'CONTAINER=$(docker ps --filter "name=gateway" --format "{{{{.Names}}}}" | head -1) && docker cp $CONTAINER:{PROD_DB_PATH} {tmp_path}'
        subprocess.run(["ssh", PROD_HOST, cmd], check=True, capture_output=True, timeout=30)
        LOCAL_DB.unlink(missing_ok=True)
        subprocess.run(["scp", f"{PROD_HOST}:{tmp_path}", str(LOCAL_DB)], check=True, capture_output=True, timeout=30)
        subprocess.run(["ssh", PROD_HOST, f"rm {tmp_path}"], capture_output=True, timeout=10)
        return True, f"Synced {LOCAL_DB.stat().st_size / 1024:.1f} KB"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode() if e.stderr else str(e)
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=60)
def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT *, datetime(timestamp, 'localtime') as local_time FROM metrics_event ORDER BY timestamp",
        conn,
    )
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["local_time"] = pd.to_datetime(df["local_time"])
    return df


def filter_data(df: pd.DataFrame, date_range: tuple, models: list[str]) -> pd.DataFrame:
    start, end = date_range
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) + pd.Timedelta(days=1)
    mask = (df["local_time"] >= start_dt) & (df["local_time"] < end_dt)
    if models and "All" not in models:
        mask &= df["model_slug"].isin(models) | df["model_slug"].isna()
    return df[mask]


# === Stats sections (matching analyze_metrics.py) ===


def show_event_counts(df: pd.DataFrame):
    """Event counts bar chart."""
    counts = df["event_type"].value_counts()

    st.markdown("#### Event Counts")
    fig = px.bar(
        x=counts.values,
        y=counts.index,
        orientation="h",
        color=counts.values,
        color_continuous_scale=[[0, COLORS["accent4"]], [1, COLORS["accent"]]],
    )
    fig.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        margin=dict(l=0, r=10, t=0, b=0),
        height=max(200, len(counts) * 28),
        xaxis_title="",
        yaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def show_latency_stats(df: pd.DataFrame):
    """Latency stats by model."""
    synthesis = df[df["event_type"] == "synthesis_complete"]
    if synthesis.empty:
        st.caption("No synthesis_complete events (latency data unavailable)")
        return

    st.markdown("#### Latency by Model")
    st.caption("Queue wait: time in Redis queue | Worker: TTS processing time")

    rows = []
    for model in synthesis["model_slug"].dropna().unique():
        model_data = synthesis[synthesis["model_slug"] == model]
        worker = model_data["worker_latency_ms"].dropna()
        queue = model_data["queue_wait_ms"].dropna()

        if worker.empty:
            continue

        rows.append(
            {
                "Model": model,
                "Count": len(model_data),
                "P50 Worker": f"{worker.quantile(0.5):.0f}ms",
                "P95 Worker": f"{worker.quantile(0.95):.0f}ms",
                "P50 Queue": f"{queue.quantile(0.5):.0f}ms" if len(queue) > 0 else "-",
                "P95 Queue": f"{queue.quantile(0.95):.0f}ms" if len(queue) > 0 else "-",
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def show_usage_stats(df: pd.DataFrame):
    """Usage stats: characters and audio duration by model."""
    # Get synthesis data - use complete for audio_duration, queued for text_length
    complete = df[df["event_type"] == "synthesis_complete"]
    queued = df[df["event_type"] == "synthesis_queued"]

    if complete.empty and queued.empty:
        return

    st.markdown("#### Usage by Model")

    rows = []
    models = set()
    if not complete.empty:
        models.update(complete["model_slug"].dropna().unique())
    if not queued.empty:
        models.update(queued["model_slug"].dropna().unique())

    for model in sorted(models):
        model_complete = complete[complete["model_slug"] == model] if not complete.empty else pd.DataFrame()
        model_queued = queued[queued["model_slug"] == model] if not queued.empty else pd.DataFrame()

        # Characters from queued events (text_length)
        chars = model_queued["text_length"].sum() if not model_queued.empty else 0

        # Audio duration from complete events
        audio_ms = model_complete["audio_duration_ms"].sum() if not model_complete.empty else 0
        audio_min = audio_ms / 60000

        # Synthesis count
        synth_count = len(model_queued)

        rows.append(
            {
                "Model": model,
                "Blocks": synth_count,
                "Characters": f"{chars:,}",
                "Audio": f"{audio_min:.1f} min",
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def show_queue_stats(df: pd.DataFrame):
    """Queue depth and overflow stats."""
    queued = df[df["event_type"] == "synthesis_queued"]
    cache_hits = df[df["event_type"] == "cache_hit"]

    col1, col2, col3, col4 = st.columns(4)

    if not queued.empty:
        depths = queued["queue_depth"].dropna()
        with col1:
            st.metric("Avg Queue Depth", f"{depths.mean():.1f}" if len(depths) > 0 else "-")
        with col2:
            st.metric("Max Queue Depth", f"{depths.max():.0f}" if len(depths) > 0 else "-")
        with col3:
            overflow = len(queued[queued["processor_route"] == "overflow"])
            local = len(queued[queued["processor_route"] == "local"])
            total = overflow + local
            pct = overflow / total * 100 if total > 0 else 0
            st.metric("Overflow", f"{overflow} ({pct:.1f}%)")

    with col4:
        total_req = len(queued) + len(cache_hits)
        rate = len(cache_hits) / total_req * 100 if total_req > 0 else 0
        st.metric("Cache Hit Rate", f"{rate:.1f}%")


def show_eviction_stats(df: pd.DataFrame):
    """Eviction events."""
    triggered = len(df[df["event_type"] == "eviction_triggered"])
    skipped = len(df[df["event_type"] == "eviction_skipped"])

    if triggered == 0 and skipped == 0:
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Evictions Triggered", triggered)
    with col2:
        st.metric("Jobs Skipped", skipped)


# === Charts ===


def chart_synthesis_scatter(df: pd.DataFrame) -> go.Figure | None:
    """Worker time over time, colored by text length."""
    synthesis = df[df["event_type"] == "synthesis_complete"].dropna(subset=["worker_latency_ms", "text_length"])
    if synthesis.empty:
        return None

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Worker Time (color=text length)", "Text Length Over Time"])

    models = list(synthesis["model_slug"].dropna().unique())

    # Left: worker time, color by text length (no legend - colorscale doesn't match model colors)
    fig.add_trace(
        go.Scatter(
            x=synthesis["local_time"],
            y=synthesis["worker_latency_ms"],
            mode="markers",
            showlegend=False,
            marker=dict(
                size=8,
                color=synthesis["text_length"],
                colorscale=[[0, COLORS["accent4"]], [0.5, COLORS["accent2"]], [1, COLORS["accent3"]]],
                showscale=True,
                colorbar=dict(title="Text Len", x=0.45),
            ),
            hovertemplate="<b>%{y:.0f}ms</b><br>Text: %{marker.color:.0f} chars<br>%{x}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Right: text length over time (with legend, model colors)
    for model in models:
        model_data = synthesis[synthesis["model_slug"] == model]
        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["text_length"],
                mode="markers",
                name=model,
                marker=dict(size=8, color=get_model_color(model)),
                legendgroup=model,
            ),
            row=1,
            col=2,
        )

    fig.update_layout(height=400, margin=dict(t=40, b=40))
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_xaxes(title_text="Time", row=1, col=2)
    fig.update_yaxes(title_text="Worker Time (ms)", row=1, col=1)
    fig.update_yaxes(title_text="Text Length (chars)", row=1, col=2)
    return fig


def chart_synthesis_ratio(df: pd.DataFrame) -> go.Figure | None:
    """Synthesis ratio: scatter over time + histogram distribution."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    synthesis = synthesis.dropna(subset=["worker_latency_ms", "audio_duration_ms"])
    synthesis = synthesis[synthesis["audio_duration_ms"] > 0]
    if synthesis.empty:
        return None

    synthesis["ratio"] = synthesis["worker_latency_ms"] / synthesis["audio_duration_ms"]
    median_ratio = synthesis["ratio"].median()

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Synthesis Speed Over Time", "Synthesis Ratio Distribution"],
        column_widths=[0.55, 0.45],
    )

    # Left: scatter over time
    for model in synthesis["model_slug"].dropna().unique():
        model_data = synthesis[synthesis["model_slug"] == model]
        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["ratio"],
                mode="markers",
                name=model,
                marker=dict(size=8, color=get_model_color(model)),
                hovertemplate="<b>%{y:.2f}x</b><br>%{x}<extra>%{fullData.name}</extra>",
            ),
            row=1,
            col=1,
        )

    # Right: histogram
    fig.add_trace(
        go.Histogram(
            x=synthesis["ratio"],
            nbinsx=15,
            marker_color=COLORS["accent4"],
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Real-time threshold lines (both subplots)
    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["error"], row=1, col=1)
    fig.add_vline(
        x=1.0,
        line_dash="dash",
        line_color=COLORS["error"],
        row=1,
        col=2,
        annotation_text="Real-time",
        annotation_position="top right",
    )

    # Median line on histogram
    fig.add_vline(
        x=median_ratio,
        line_dash="solid",
        line_color=COLORS["accent"],
        row=1,
        col=2,
        annotation_text=f"Median: {median_ratio:.2f}",
        annotation_position="top left",
    )

    fig.update_layout(
        title="Synthesis Speed (ratio < 1 = faster than real-time)",
        height=380,
        margin=dict(t=60),
    )
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_xaxes(title_text="Synthesis Ratio", row=1, col=2)
    fig.update_yaxes(title_text="Ratio (worker / audio)", row=1, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=2)
    return fig


def chart_latency_breakdown(df: pd.DataFrame) -> go.Figure | None:
    """Stacked bar: queue wait vs worker time over time."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    synthesis = synthesis.dropna(subset=["queue_wait_ms", "worker_latency_ms"])
    if synthesis.empty:
        return None

    # Bin by 10-minute intervals
    synthesis["bin"] = synthesis["local_time"].dt.floor("10min")
    grouped = (
        synthesis.groupby("bin")
        .agg(
            queue_wait=("queue_wait_ms", "mean"),
            worker_time=("worker_latency_ms", "mean"),
            count=("id", "count"),
        )
        .reset_index()
    )

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=grouped["bin"],
            y=grouped["queue_wait"],
            name="Queue Wait",
            marker_color=COLORS["accent4"],
            hovertemplate="Queue: %{y:.0f}ms<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=grouped["bin"],
            y=grouped["worker_time"],
            name="Worker Time",
            marker_color=COLORS["accent"],
            hovertemplate="Worker: %{y:.0f}ms<extra></extra>",
        )
    )

    fig.update_layout(
        title="Latency Breakdown (10-min avg)",
        barmode="stack",
        height=350,
        xaxis_title="Time",
        yaxis_title="Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_model_usage(df: pd.DataFrame) -> go.Figure | None:
    """Model and route usage."""
    queued = df[df["event_type"] == "synthesis_queued"]
    cache_hits = df[df["event_type"] == "cache_hit"]

    if queued.empty and cache_hits.empty:
        return None

    fig = make_subplots(rows=1, cols=2, subplot_titles=["By Model", "By Route"], vertical_spacing=0.15)

    # Left: by model (synthesized vs cached)
    if not queued.empty:
        model_counts = queued["model_slug"].value_counts()
        cache_by_model = cache_hits["model_slug"].value_counts()
        models = sorted(set(model_counts.index) | set(cache_by_model.index))

        synth_vals = [model_counts.get(m, 0) for m in models]
        cache_vals = [cache_by_model.get(m, 0) for m in models]
        colors = [get_model_color(m) for m in models]

        fig.add_trace(
            go.Bar(
                x=models,
                y=synth_vals,
                name="Synthesized",
                marker_color=colors,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=models,
                y=cache_vals,
                name="Cache Hit",
                marker_color=colors,
                marker_pattern_shape="/",
                opacity=0.6,
            ),
            row=1,
            col=1,
        )

    # Right: by route
    if not queued.empty and "processor_route" in queued.columns:
        route_counts = queued["processor_route"].value_counts()
        route_colors = [COLORS["local"] if r == "local" else COLORS["overflow"] for r in route_counts.index]

        fig.add_trace(
            go.Bar(
                x=list(route_counts.index),
                y=list(route_counts.values),
                marker_color=route_colors,
                showlegend=False,
                text=[f"{v} ({v / route_counts.sum() * 100:.0f}%)" for v in route_counts.values],
                textposition="outside",
            ),
            row=1,
            col=2,
        )

    fig.update_layout(
        height=400,
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60),
    )
    return fig


def chart_queue_metrics(df: pd.DataFrame) -> go.Figure | None:
    """Queue depth and wait time over time."""
    queued = df[df["event_type"] == "synthesis_queued"]
    complete = df[df["event_type"] == "synthesis_complete"]

    if queued.empty:
        return None

    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=["Queue Depth at Enqueue", "Queue Wait Time"],
        shared_xaxes=True,
        vertical_spacing=0.12,
    )

    # Queue depth
    if "queue_depth" in queued.columns:
        fig.add_trace(
            go.Scatter(
                x=queued["local_time"],
                y=queued["queue_depth"],
                mode="markers",
                marker=dict(size=6, color=COLORS["accent4"]),
                name="Queue Depth",
                hovertemplate="Depth: %{y}<br>%{x}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # Queue wait from complete events
    if not complete.empty and "queue_wait_ms" in complete.columns:
        wait_data = complete.dropna(subset=["queue_wait_ms"])
        if not wait_data.empty:
            fig.add_trace(
                go.Scatter(
                    x=wait_data["local_time"],
                    y=wait_data["queue_wait_ms"],
                    mode="markers",
                    marker=dict(size=6, color=COLORS["accent"]),
                    name="Wait Time",
                    hovertemplate="Wait: %{y:.0f}ms<br>%{x}<extra></extra>",
                ),
                row=2,
                col=1,
            )

    fig.update_layout(height=450, showlegend=False)
    fig.update_yaxes(title_text="Depth", row=1, col=1)
    fig.update_yaxes(title_text="Wait (ms)", row=2, col=1)
    fig.update_xaxes(title_text="Time", row=2, col=1)
    return fig


# === Main ===


def main():
    st.set_page_config(page_title="Yapit Metrics", layout="wide")
    st.title("📊 Yapit TTS Metrics")

    # Sidebar
    with st.sidebar:
        st.header("Controls")

        if st.button("🔄 Sync from Prod", use_container_width=True):
            with st.spinner("Syncing..."):
                ok, msg = sync_from_prod()
                if ok:
                    st.success(msg)
                    st.cache_data.clear()
                else:
                    st.error(msg)

        st.divider()

        if not LOCAL_DB.exists():
            st.warning("No metrics.db - click Sync")
            return

        st.caption(f"DB: {LOCAL_DB.stat().st_size / 1024:.1f} KB")
        st.caption(f"Modified: {datetime.fromtimestamp(LOCAL_DB.stat().st_mtime).strftime('%m-%d %H:%M')}")

        df = load_data(str(LOCAL_DB))
        if df.empty:
            st.warning("Empty database")
            return

        st.divider()
        st.subheader("Filters")

        min_date = df["local_time"].min().date()
        max_date = df["local_time"].max().date()
        default_start = max(min_date, max_date - timedelta(days=7))

        date_range = st.date_input(
            "Date Range",
            value=(default_start, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        if not isinstance(date_range, tuple) or len(date_range) != 2:
            date_range = (
                (date_range, date_range) if not isinstance(date_range, tuple) else (date_range[0], date_range[0])
            )

        models = ["All"] + sorted(df["model_slug"].dropna().unique().tolist())
        selected_models = st.multiselect("Models", models, default=["All"])

    # Filter
    filtered = filter_data(df, date_range, selected_models)
    if filtered.empty:
        st.warning("No data for selected filters")
        return

    # Time range display
    time_span = filtered["local_time"].max() - filtered["local_time"].min()
    st.caption(f"Showing {len(filtered)} events over {time_span}")

    # Stats section
    st.header("Summary")
    show_queue_stats(filtered)
    show_eviction_stats(filtered)

    st.divider()

    # Three columns: event counts, usage stats, latency stats
    col1, col2, col3 = st.columns(3)
    with col1:
        show_event_counts(filtered)
    with col2:
        show_usage_stats(filtered)
    with col3:
        show_latency_stats(filtered)

    st.divider()

    # Charts
    st.header("Charts")

    # Row 1: synthesis scatter (wide)
    fig = chart_synthesis_scatter(filtered)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Synthesis scatter: no synthesis_complete data")

    # Row 2: synthesis ratio (wide - has scatter + histogram)
    fig = chart_synthesis_ratio(filtered)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Synthesis ratio: no synthesis_complete data")

    # Row 3: latency breakdown (if data available)
    fig = chart_latency_breakdown(filtered)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Row 3: model usage + queue metrics
    col1, col2 = st.columns(2)
    with col1:
        fig = chart_model_usage(filtered)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Model usage: no data")

    with col2:
        fig = chart_queue_metrics(filtered)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Queue metrics: no data")

    # Raw data
    with st.expander("Raw Data"):
        st.dataframe(filtered.tail(100), use_container_width=True)


if __name__ == "__main__":
    main()
