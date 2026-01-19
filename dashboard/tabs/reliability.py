"""Reliability tab - Retries, DLQ, overflow, incomplete jobs."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, calculate_rate, get_events
from dashboard.theme import COLORS, apply_plotly_theme


def _summary_stats(df: pd.DataFrame):
    """Display reliability summary."""
    requeued = get_events(df, "job_requeued")
    dlq = get_events(df, "job_dlq")
    overflow = get_events(df, "job_overflow")
    overflow_complete = get_events(df, "overflow_complete")
    overflow_error = get_events(df, "overflow_error")

    # Calculate incomplete jobs (synthesis only for now)
    queued_hashes = set(get_events(df, "synthesis_queued")["variant_hash"].dropna())
    completed_hashes = set(get_events(df, "synthesis_complete")["variant_hash"].dropna())
    errored_hashes = set(get_events(df, "synthesis_error")["variant_hash"].dropna())
    finished_hashes = completed_hashes | errored_hashes
    incomplete = queued_hashes - finished_hashes

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Requeued Jobs", format_number(len(requeued)), help="Jobs requeued due to visibility timeout")
    with col2:
        st.metric("Dead Letter Queue", format_number(len(dlq)), help="Jobs that exceeded max retries")
    with col3:
        st.metric("Overflow Jobs", format_number(len(overflow)), help="Jobs sent to serverless")
    with col4:
        overflow_total = len(overflow_complete) + len(overflow_error)
        overflow_success = calculate_rate(len(overflow_complete), len(overflow_error)) if overflow_total > 0 else 100
        st.metric("Overflow Success", format_percent(overflow_success))
    with col5:
        st.metric("Incomplete Jobs", format_number(len(incomplete)), help="Queued but never finished")


def _retry_timeline(df: pd.DataFrame) -> go.Figure | None:
    """Retry events over time."""
    requeued = get_events(df, "job_requeued")
    if requeued.empty:
        return None

    requeued = bin_by_time(requeued, "1h")
    hourly = requeued.groupby("time_bin").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["count"],
            mode="lines+markers",
            line=dict(color=COLORS["warning"], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(210, 153, 34, 0.15)",
            hovertemplate="%{y} requeued<extra></extra>",
        )
    )

    fig.update_layout(
        title="Job Requeues Over Time (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Requeued Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _dlq_timeline(df: pd.DataFrame) -> go.Figure | None:
    """DLQ events over time."""
    dlq = get_events(df, "job_dlq")
    if dlq.empty:
        return None

    dlq = bin_by_time(dlq, "1h")
    hourly = dlq.groupby("time_bin").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["count"],
            mode="lines+markers",
            line=dict(color=COLORS["error"], width=2),
            marker=dict(size=8),
            fill="tozeroy",
            fillcolor="rgba(248, 81, 73, 0.15)",
            hovertemplate="%{y} to DLQ<extra></extra>",
        )
    )

    fig.update_layout(
        title="Dead Letter Queue Events (hourly) - Should Be Zero!",
        height=300,
        xaxis_title="Time",
        yaxis_title="DLQ Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _retry_count_histogram(df: pd.DataFrame) -> go.Figure | None:
    """Distribution of retry counts."""
    requeued = get_events(df, "job_requeued")
    dlq = get_events(df, "job_dlq")

    events = pd.concat([requeued, dlq], ignore_index=True)
    if events.empty or "retry_count" not in events.columns:
        return None

    retry_counts = events["retry_count"].dropna()
    if retry_counts.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=retry_counts,
            nbinsx=int(retry_counts.max()) + 1 if not retry_counts.empty else 5,
            marker=dict(color=COLORS["warning"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Retry #%{x}<br>Count: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Retry Count Distribution",
        height=300,
        xaxis_title="Retry Count",
        yaxis_title="Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _overflow_comparison(df: pd.DataFrame) -> go.Figure | None:
    """Overflow vs local processing comparison."""
    # Get synthesis events
    synthesis = get_events(df, "synthesis_complete")
    overflow_complete = get_events(df, "overflow_complete")

    if synthesis.empty and overflow_complete.empty:
        return None

    # Count by queue_type or other indicator
    local_count = len(synthesis)  # Simplified - actual distinction may need different logic
    overflow_count = len(get_events(df, "job_overflow"))

    total = local_count + overflow_count
    if total == 0:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Pie(
            labels=["Local", "Overflow"],
            values=[local_count, overflow_count],
            marker=dict(colors=[COLORS["accent_teal"], COLORS["accent_coral"]]),
            hole=0.4,
            textinfo="label+percent",
            hovertemplate="%{label}: %{value:,}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Local vs Overflow Processing",
        height=300,
        showlegend=False,
    )
    apply_plotly_theme(fig)
    return fig


def _overflow_timeline(df: pd.DataFrame) -> go.Figure | None:
    """Overflow events over time."""
    overflow = get_events(df, "job_overflow")
    if overflow.empty:
        return None

    overflow = bin_by_time(overflow, "1h")
    hourly = overflow.groupby("time_bin").size().reset_index(name="sent")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=hourly["time_bin"],
            y=hourly["sent"],
            name="Sent to Overflow",
            marker_color=COLORS["accent_coral"],
            hovertemplate="%{y} jobs<extra></extra>",
        )
    )

    fig.update_layout(
        title="Overflow Usage Over Time (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _incomplete_jobs_chart(df: pd.DataFrame) -> go.Figure | None:
    """Incomplete jobs over time."""
    queued = get_events(df, "synthesis_queued").copy()
    completed = get_events(df, "synthesis_complete")
    errored = get_events(df, "synthesis_error")

    if queued.empty:
        return None

    completed_hashes = set(completed["variant_hash"].dropna())
    errored_hashes = set(errored["variant_hash"].dropna())
    finished_hashes = completed_hashes | errored_hashes

    queued["incomplete"] = ~queued["variant_hash"].isin(finished_hashes)
    incomplete = queued[queued["incomplete"]]

    if incomplete.empty:
        return None

    incomplete = bin_by_time(incomplete, "1h")
    hourly = incomplete.groupby("time_bin").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["count"],
            mode="lines+markers",
            line=dict(color=COLORS["text_muted"], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(110, 118, 129, 0.15)",
            hovertemplate="%{y} incomplete<extra></extra>",
        )
    )

    fig.update_layout(
        title="Incomplete Jobs Over Time (queued but never finished)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Incomplete Jobs",
    )
    apply_plotly_theme(fig)
    return fig


def _reliability_by_queue(df: pd.DataFrame):
    """Reliability stats by queue type."""
    requeued = get_events(df, "job_requeued")
    dlq = get_events(df, "job_dlq")

    all_events = pd.concat([requeued, dlq], ignore_index=True)
    if all_events.empty or "queue_type" not in all_events.columns:
        st.caption("No queue type data")
        return

    stats = (
        all_events.groupby("queue_type")
        .agg(
            requeued=("event_type", lambda x: (x == "job_requeued").sum()),
            dlq=("event_type", lambda x: (x == "job_dlq").sum()),
        )
        .reset_index()
    )

    display_df = pd.DataFrame(
        {
            "Queue": stats["queue_type"],
            "Requeued": stats["requeued"],
            "DLQ": stats["dlq"],
        }
    )

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def render(df: pd.DataFrame):
    """Render the Reliability tab."""
    # Summary stats (always show - even if zeros)
    section_header("Summary", "Reliability metrics")
    _summary_stats(df)

    st.divider()

    # By queue type
    section_header("By Queue Type", "Reliability breakdown")
    _reliability_by_queue(df)

    st.divider()

    # Charts
    section_header("Charts")

    # Row 1: Retry + DLQ timelines
    col1, col2 = st.columns(2)
    with col1:
        fig = _retry_timeline(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No retry events (great!)")

    with col2:
        fig = _dlq_timeline(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No DLQ events (great!)")

    # Row 2: Retry distribution + overflow comparison
    col1, col2 = st.columns(2)
    with col1:
        fig = _retry_count_histogram(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No retry count data")

    with col2:
        fig = _overflow_comparison(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No overflow data")

    # Row 3: Overflow timeline + incomplete jobs
    col1, col2 = st.columns(2)
    with col1:
        fig = _overflow_timeline(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No overflow usage")

    with col2:
        fig = _incomplete_jobs_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No incomplete jobs (great!)")
