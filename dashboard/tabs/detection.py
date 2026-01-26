"""Detection tab - YOLO/figure detection performance metrics."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_duration,
    format_number,
    section_header,
)
from dashboard.data import bin_by_time, get_events
from dashboard.theme import COLORS, apply_plotly_theme


def _summary_stats(df: pd.DataFrame):
    """Display summary statistics."""
    queued = get_events(df, "detection_queued")
    complete = get_events(df, "detection_complete")
    errors = get_events(df, "detection_error")
    mismatches = get_events(df, "figure_count_mismatch")

    total = len(queued)
    completed = len(complete)
    errored = len(errors)
    error_rate = (errored / (completed + errored) * 100) if (completed + errored) > 0 else 0

    # Extract figures count from data blob
    figures_total = 0
    if not complete.empty:
        figures_total = complete["data"].apply(lambda d: d.get("figures_count", 0) if isinstance(d, dict) else 0).sum()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Jobs Queued", format_number(total))
    with col2:
        st.metric("Completed", format_number(completed))
    with col3:
        st.metric("Errors", format_number(errored))
    with col4:
        st.metric("Error Rate", f"{error_rate:.1f}%")
    with col5:
        st.metric("Figures Detected", format_number(figures_total))
    with col6:
        st.metric("Figure Mismatches", format_number(len(mismatches)))


def _worker_stats_table(df: pd.DataFrame):
    """Display per-worker performance table."""
    complete = get_events(df, "detection_complete")
    errors = get_events(df, "detection_error")

    if complete.empty and errors.empty:
        st.caption("No detection data for worker breakdown")
        return

    all_events = pd.concat([complete, errors], ignore_index=True)
    if "worker_id" not in all_events.columns or all_events["worker_id"].isna().all():
        st.caption("No worker_id data available")
        return

    workers = (
        all_events.groupby("worker_id")
        .agg(
            jobs=("event_type", "count"),
            completed=("event_type", lambda x: (x == "detection_complete").sum()),
            errors=("event_type", lambda x: (x == "detection_error").sum()),
            p50_latency=("worker_latency_ms", lambda x: x.quantile(0.5)),
            p95_latency=("worker_latency_ms", lambda x: x.quantile(0.95)),
            figures=("data", lambda x: sum(d.get("figures_count", 0) for d in x if isinstance(d, dict))),
        )
        .reset_index()
    )

    display_df = pd.DataFrame(
        {
            "Worker": workers["worker_id"],
            "Jobs": workers["jobs"],
            "Completed": workers["completed"],
            "Errors": workers["errors"],
            "P50 Latency": workers["p50_latency"].apply(format_duration),
            "P95 Latency": workers["p95_latency"].apply(format_duration),
            "Figures": workers["figures"],
        }
    )

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def _throughput_chart(df: pd.DataFrame) -> go.Figure | None:
    """Detection throughput over time."""
    complete = get_events(df, "detection_complete")
    if complete.empty:
        return None

    complete = bin_by_time(complete, "1h")
    hourly = complete.groupby("time_bin").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["count"],
            mode="lines+markers",
            line=dict(color=COLORS["accent_purple"], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(163, 113, 247, 0.15)",
            hovertemplate="%{y} detections<extra></extra>",
        )
    )

    fig.update_layout(
        title="Detection Throughput (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Completed Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _latency_histogram(df: pd.DataFrame) -> go.Figure | None:
    """Detection latency distribution."""
    complete = get_events(df, "detection_complete")
    if complete.empty:
        return None

    latencies = complete["worker_latency_ms"].dropna()
    if latencies.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=latencies,
            nbinsx=30,
            marker=dict(color=COLORS["accent_purple"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Latency: %{x:.0f}ms<br>Count: %{y}<extra></extra>",
        )
    )

    median = latencies.median()
    fig.add_vline(
        x=median,
        line_dash="dash",
        line_color=COLORS["accent_teal"],
        annotation_text=f"Median: {format_duration(median)}",
        annotation_position="top right",
    )

    fig.update_layout(
        title="Detection Latency Distribution",
        height=300,
        xaxis_title="Latency (ms)",
        yaxis_title="Count",
    )
    apply_plotly_theme(fig)
    return fig


def _queue_depth_chart(df: pd.DataFrame) -> go.Figure | None:
    """Queue depth over time."""
    queued = get_events(df, "detection_queued")
    if queued.empty or "queue_depth" not in queued.columns:
        return None

    queued = queued.dropna(subset=["queue_depth"])
    if queued.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=queued["local_time"],
            y=queued["queue_depth"],
            mode="markers",
            marker=dict(size=6, color=COLORS["accent_purple"]),
            hovertemplate="Depth: %{y}<br>%{x}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Detection Queue Depth at Enqueue",
        height=300,
        xaxis_title="Time",
        yaxis_title="Queue Depth",
    )
    apply_plotly_theme(fig)
    return fig


def _figures_per_page_chart(df: pd.DataFrame) -> go.Figure | None:
    """Figures detected per page histogram."""
    complete = get_events(df, "detection_complete")
    if complete.empty:
        return None

    figures = complete["data"].apply(lambda d: d.get("figures_count", 0) if isinstance(d, dict) else 0)
    if figures.empty or figures.sum() == 0:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=figures,
            nbinsx=max(int(figures.max()) + 1, 10),
            marker=dict(color=COLORS["accent_cyan"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Figures: %{x}<br>Pages: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Figures Detected Per Page",
        height=300,
        xaxis_title="Figures Count",
        yaxis_title="Number of Pages",
    )
    apply_plotly_theme(fig)
    return fig


def _figure_mismatch_chart(df: pd.DataFrame) -> go.Figure | None:
    """Figure count mismatch: YOLO vs Gemini placeholders."""
    mismatches = get_events(df, "figure_count_mismatch")
    if mismatches.empty:
        return None

    # Extract counts from data blob
    mismatches = mismatches.copy()
    mismatches["yolo_count"] = mismatches["data"].apply(lambda d: d.get("yolo_count", 0) if isinstance(d, dict) else 0)
    mismatches["gemini_count"] = mismatches["data"].apply(
        lambda d: d.get("gemini_count", 0) if isinstance(d, dict) else 0
    )
    mismatches["delta"] = mismatches["data"].apply(lambda d: d.get("delta", 0) if isinstance(d, dict) else 0)

    fig = go.Figure()

    # Scatter: x=YOLO count, y=Gemini count, color by direction of mismatch
    # Points above diagonal = Gemini hallucinated, below = Gemini missed
    colors = mismatches["delta"].apply(lambda d: COLORS["error"] if d > 0 else COLORS["accent_teal"])

    fig.add_trace(
        go.Scatter(
            x=mismatches["yolo_count"],
            y=mismatches["gemini_count"],
            mode="markers",
            marker=dict(size=10, color=colors, opacity=0.7, line=dict(width=1, color=COLORS["border"])),
            hovertemplate="YOLO: %{x}<br>Gemini: %{y}<br>Delta: %{customdata}<extra></extra>",
            customdata=mismatches["delta"],
        )
    )

    # Add diagonal reference line (perfect match)
    max_val = max(mismatches["yolo_count"].max(), mismatches["gemini_count"].max(), 1) + 1
    fig.add_trace(
        go.Scatter(
            x=[0, max_val],
            y=[0, max_val],
            mode="lines",
            line=dict(color=COLORS["muted"], width=1, dash="dash"),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        title="Figure Count: YOLO vs Gemini",
        height=300,
        xaxis_title="YOLO Detected",
        yaxis_title="Gemini Placeholders",
        annotations=[
            dict(
                x=0.02,
                y=0.98,
                xref="paper",
                yref="paper",
                text=f"<span style='color:{COLORS['error']}'>● Gemini extra</span>  "
                f"<span style='color:{COLORS['accent_teal']}'>● Gemini missed</span>",
                showarrow=False,
                font=dict(size=10),
                align="left",
            )
        ],
    )
    apply_plotly_theme(fig)
    return fig


def _latency_over_time(df: pd.DataFrame) -> go.Figure | None:
    """Latency scatter over time."""
    complete = get_events(df, "detection_complete")
    complete = complete.dropna(subset=["worker_latency_ms"])
    if complete.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=complete["local_time"],
            y=complete["worker_latency_ms"],
            mode="markers",
            marker=dict(size=6, color=COLORS["accent_purple"], opacity=0.7),
            hovertemplate="Latency: %{y:.0f}ms<br>%{x}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Detection Latency Over Time",
        height=300,
        xaxis_title="Time",
        yaxis_title="Latency (ms)",
    )
    apply_plotly_theme(fig)
    return fig


def render(df: pd.DataFrame):
    """Render the Detection tab."""
    detection_events = get_events(df, "detection_queued")
    if detection_events.empty and get_events(df, "detection_complete").empty:
        empty_state("No detection data available", icon="🔍")
        return

    # Summary stats
    section_header("Summary", "Detection job statistics")
    _summary_stats(df)

    st.divider()

    # Per-worker breakdown
    section_header("Per-Worker Performance", "Individual worker statistics")
    _worker_stats_table(df)

    st.divider()

    # Charts
    section_header("Charts")

    # Row 1: Throughput
    fig = _throughput_chart(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No throughput data")

    # Row 2: Latency over time + histogram
    col1, col2 = st.columns(2)
    with col1:
        fig = _latency_over_time(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No latency data")

    with col2:
        fig = _latency_histogram(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No latency data")

    # Row 3: Queue depth + figures per page
    col1, col2 = st.columns(2)
    with col1:
        fig = _queue_depth_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No queue depth data")

    with col2:
        fig = _figures_per_page_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No figures data")

    # Row 4: Figure count mismatch
    fig = _figure_mismatch_chart(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
