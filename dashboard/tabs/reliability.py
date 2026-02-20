"""Reliability tab - Retries, DLQ, overflow, incomplete jobs."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    format_duration,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, calculate_rate, get_events
from dashboard.theme import COLORS, apply_plotly_theme

# === Stripe Webhook Functions ===


def _webhook_stats(df: pd.DataFrame):
    """Display Stripe webhook summary stats."""
    webhooks = get_events(df, "stripe_webhook")
    if webhooks.empty:
        st.caption("No Stripe webhook events logged yet")
        return

    # Extract data from blob
    webhooks = webhooks.copy()
    webhooks["duration_ms"] = webhooks["data"].apply(lambda d: d.get("duration_ms") if isinstance(d, dict) else None)
    webhooks["event_type"] = webhooks["data"].apply(lambda d: d.get("event_type") if isinstance(d, dict) else None)
    webhooks["has_error"] = webhooks["data"].apply(lambda d: "error" in d if isinstance(d, dict) else False)

    total = len(webhooks)
    errors = webhooks["has_error"].sum()
    error_rate = errors / total * 100 if total > 0 else 0

    latencies = webhooks["duration_ms"].dropna()
    p50 = latencies.quantile(0.5) if not latencies.empty else 0
    p95 = latencies.quantile(0.95) if not latencies.empty else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Webhooks", format_number(total))
    with col2:
        st.metric("Errors", format_number(errors))
    with col3:
        st.metric("Error Rate", format_percent(error_rate))
    with col4:
        st.metric("P50 Latency", format_duration(p50))
    with col5:
        st.metric("P95 Latency", format_duration(p95))
        if p95 > 10000:
            st.caption("⚠️ >10s (Stripe times out at 20s)")


def _webhook_latency_chart(df: pd.DataFrame) -> go.Figure | None:
    """Webhook latency histogram."""
    webhooks = get_events(df, "stripe_webhook")
    if webhooks.empty:
        return None

    webhooks = webhooks.copy()
    webhooks["duration_ms"] = webhooks["data"].apply(lambda d: d.get("duration_ms") if isinstance(d, dict) else None)
    latencies = webhooks["duration_ms"].dropna()

    if latencies.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=latencies,
            nbinsx=30,
            marker=dict(color=COLORS["accent_blue"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Latency: %{x:.0f}ms<br>Count: %{y}<extra></extra>",
        )
    )

    # Add warning line at 10s
    fig.add_vline(
        x=10000,
        line_dash="dash",
        line_color=COLORS["warning"],
        annotation_text="10s",
        annotation_position="top right",
    )

    # Add danger line at 20s (Stripe timeout)
    fig.add_vline(
        x=20000,
        line_dash="dash",
        line_color=COLORS["error"],
        annotation_text="20s (timeout)",
        annotation_position="top right",
    )

    fig.update_layout(
        title="Webhook Handler Latency",
        height=300,
        xaxis_title="Latency (ms)",
        yaxis_title="Count",
    )
    apply_plotly_theme(fig)
    return fig


def _webhook_errors_chart(df: pd.DataFrame) -> go.Figure | None:
    """Webhook errors over time."""
    webhooks = get_events(df, "stripe_webhook")
    if webhooks.empty:
        return None

    webhooks = webhooks.copy()
    webhooks["has_error"] = webhooks["data"].apply(lambda d: "error" in d if isinstance(d, dict) else False)

    errors = webhooks[webhooks["has_error"]]
    if errors.empty:
        return None

    errors = bin_by_time(errors, "1h")
    hourly = errors.groupby("time_bin").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["count"],
            mode="lines+markers",
            line=dict(color=COLORS["error"], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(248, 81, 73, 0.15)",
            hovertemplate="%{y} errors<extra></extra>",
        )
    )

    fig.update_layout(
        title="Webhook Errors Over Time (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Errors",
    )
    apply_plotly_theme(fig)
    return fig


def _summary_stats(df: pd.DataFrame):
    """Display reliability summary."""
    requeued = get_events(df, "job_requeued")
    dlq = get_events(df, "job_dlq")
    overflow = get_events(df, "job_overflow")
    overflow_complete = get_events(df, "overflow_complete")
    overflow_error = get_events(df, "overflow_error")
    rate_limits = get_events(df, "api_rate_limit")

    # Calculate incomplete jobs (synthesis only for now)
    queued_hashes = set(get_events(df, "synthesis_queued")["variant_hash"].dropna())
    completed_hashes = set(get_events(df, "synthesis_complete")["variant_hash"].dropna())
    errored_hashes = set(get_events(df, "synthesis_error")["variant_hash"].dropna())
    finished_hashes = completed_hashes | errored_hashes
    incomplete = queued_hashes - finished_hashes

    col1, col2, col3, col4, col5, col6 = st.columns(6)
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
    with col6:
        rl_by_api = rate_limits["data"].apply(
            lambda d: d.get("api_name", "unknown") if isinstance(d, dict) else "unknown"
        )
        rl_breakdown = rl_by_api.value_counts().to_dict() if not rate_limits.empty else {}
        help_parts = [f"{name}: {count}" for name, count in rl_breakdown.items()]
        st.metric(
            "API Rate Limits",
            format_number(len(rate_limits)),
            help=", ".join(help_parts) if help_parts else "429 responses from Gemini/Inworld",
        )


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


def _rate_limit_timeline(df: pd.DataFrame) -> go.Figure | None:
    """API rate limit (429) events over time, by API."""
    rate_limits = get_events(df, "api_rate_limit")
    if rate_limits.empty:
        return None

    rate_limits = rate_limits.copy()
    rate_limits["api_name"] = rate_limits["data"].apply(
        lambda d: d.get("api_name", "unknown") if isinstance(d, dict) else "unknown"
    )
    rate_limits = bin_by_time(rate_limits, "1h")

    api_colors = {"gemini": COLORS["accent_blue"], "inworld": COLORS["accent_coral"]}

    fig = go.Figure()
    for api_name in sorted(rate_limits["api_name"].unique()):
        api_data = rate_limits[rate_limits["api_name"] == api_name]
        hourly = api_data.groupby("time_bin").size().reset_index(name="count")
        fig.add_trace(
            go.Bar(
                x=hourly["time_bin"],
                y=hourly["count"],
                name=api_name,
                marker_color=api_colors.get(api_name, COLORS["text_muted"]),
                hovertemplate=f"{api_name}: %{{y}} rate limits<extra></extra>",
            )
        )

    fig.update_layout(
        title="API Rate Limits Over Time (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="429 Responses",
        barmode="stack",
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

    # Stripe webhooks
    section_header("Stripe Webhooks", "Webhook processing health")
    _webhook_stats(df)

    col1, col2 = st.columns(2)
    with col1:
        fig = _webhook_latency_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No webhook latency data")
    with col2:
        fig = _webhook_errors_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No webhook errors (great!)")

    st.divider()

    # API rate limits
    section_header("API Rate Limits", "429 responses from external APIs")
    fig = _rate_limit_timeline(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No rate limit events (great!)")

    st.divider()

    # By queue type
    section_header("By Queue Type", "Reliability breakdown")
    _reliability_by_queue(df)

    st.divider()

    # Charts
    section_header("Job Processing Charts")

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
