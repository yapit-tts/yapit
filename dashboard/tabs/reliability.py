"""Reliability tab — retries, DLQ, webhooks, rate limits, sessions, errors."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    format_duration,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, get_events
from dashboard.theme import COLORS, apply_plotly_theme

# ── Summary ───────────────────────────────────────────────────────────────────


def _summary_stats(df: pd.DataFrame):
    requeued = get_events(df, "job_requeued")
    dlq = get_events(df, "job_dlq")
    rate_limits = get_events(df, "api_rate_limit")
    errors = get_events(df, "error")
    warnings = get_events(df, "warning")

    # Incomplete jobs
    queued_hashes = set(get_events(df, "synthesis_queued")["variant_hash"].dropna())
    completed_hashes = set(get_events(df, "synthesis_complete")["variant_hash"].dropna())
    errored_hashes = set(get_events(df, "synthesis_error")["variant_hash"].dropna())
    incomplete = queued_hashes - completed_hashes - errored_hashes

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Requeued Jobs", format_number(len(requeued)), help="Visibility timeout requeues")
    with col2:
        st.metric("Dead Letter Queue", format_number(len(dlq)), help="Max retries exceeded")
    with col3:
        st.metric("Incomplete Jobs", format_number(len(incomplete)), help="Queued but never finished")
    with col4:
        rl_by_api = rate_limits["data"].apply(
            lambda d: d.get("api_name", "unknown") if isinstance(d, dict) else "unknown"
        )
        rl_breakdown = rl_by_api.value_counts().to_dict() if not rate_limits.empty else {}
        help_parts = [f"{name}: {count}" for name, count in rl_breakdown.items()]
        st.metric(
            "API Rate Limits",
            format_number(len(rate_limits)),
            help=", ".join(help_parts) if help_parts else "429 responses from APIs",
        )
    with col5:
        st.metric("Gateway Errors", format_number(len(errors)), help="Internal gateway errors")
    with col6:
        st.metric("Warnings", format_number(len(warnings)))


# ── WebSocket Sessions ────────────────────────────────────────────────────────


def _websocket_sessions(df: pd.DataFrame):
    connects = get_events(df, "ws_connect")
    disconnects = get_events(df, "ws_disconnect")

    if connects.empty and disconnects.empty:
        st.caption("No WebSocket session data")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Connections", format_number(len(connects)))
    with col2:
        st.metric("Disconnections", format_number(len(disconnects)))
    with col3:
        if not disconnects.empty:
            durations = (
                disconnects["data"]
                .apply(lambda d: d.get("session_duration_ms") if isinstance(d, dict) else None)
                .dropna()
            )
            if not durations.empty:
                durations = pd.to_numeric(durations, errors="coerce").dropna()
                st.metric("Median Session", format_duration(durations.median()))
                st.caption(f"P95: {format_duration(durations.quantile(0.95))}")
            else:
                st.metric("Median Session", "-")
        else:
            st.metric("Median Session", "-")

    # Sessions over time
    if not connects.empty:
        connects_binned = bin_by_time(connects, "1h")
        hourly = connects_binned.groupby("time_bin").size().reset_index(name="count")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=hourly["time_bin"],
                y=hourly["count"],
                mode="lines+markers",
                line=dict(color=COLORS["accent_cyan"], width=2),
                marker=dict(size=4),
                fill="tozeroy",
                fillcolor="rgba(86, 212, 221, 0.15)",
                hovertemplate="%{y} connections<extra></extra>",
            )
        )
        fig.update_layout(
            title="WebSocket Connections (hourly)", height=250, xaxis_title="Time", yaxis_title="Connections"
        )
        apply_plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")


# ── Stripe Webhooks ───────────────────────────────────────────────────────────


def _webhook_stats(df: pd.DataFrame):
    webhooks = get_events(df, "stripe_webhook")
    if webhooks.empty:
        st.caption("No Stripe webhook events")
        return

    webhooks = webhooks.copy()
    webhooks["wh_duration_ms"] = webhooks["data"].apply(lambda d: d.get("duration_ms") if isinstance(d, dict) else None)
    webhooks["wh_event_type"] = webhooks["data"].apply(lambda d: d.get("event_type") if isinstance(d, dict) else None)
    webhooks["has_error"] = webhooks["data"].apply(lambda d: "error" in d if isinstance(d, dict) else False)

    total = len(webhooks)
    errors = webhooks["has_error"].sum()
    error_rate = errors / total * 100 if total > 0 else 0

    latencies = pd.to_numeric(webhooks["wh_duration_ms"], errors="coerce").dropna()
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
            st.caption(">10s (Stripe times out at 20s)")

    # Latency histogram
    if not latencies.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Histogram(
                x=latencies,
                nbinsx=30,
                marker=dict(color=COLORS["accent_blue"], line=dict(width=1, color=COLORS["border"])),
                hovertemplate="Latency: %{x:.0f}ms<br>Count: %{y}<extra></extra>",
            )
        )
        fig.add_vline(
            x=10000,
            line_dash="dash",
            line_color=COLORS["warning"],
            annotation_text="10s",
            annotation_position="top right",
        )
        fig.add_vline(
            x=20000,
            line_dash="dash",
            line_color=COLORS["error"],
            annotation_text="20s (timeout)",
            annotation_position="top right",
        )
        fig.update_layout(title="Webhook Latency", height=280, xaxis_title="Latency (ms)", yaxis_title="Count")
        apply_plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")


# ── Gateway Errors ────────────────────────────────────────────────────────────


def _gateway_errors(df: pd.DataFrame):
    errors = get_events(df, "error")
    warnings = get_events(df, "warning")

    if errors.empty and warnings.empty:
        st.caption("No gateway error/warning events")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Errors", format_number(len(errors)))
    with col2:
        st.metric("Warnings", format_number(len(warnings)))

    # Show top error messages (truncated), full list in expander
    if not errors.empty:
        messages = errors["data"].apply(lambda d: d.get("message", "unknown") if isinstance(d, dict) else "unknown")
        msg_counts = messages.value_counts()
        # Show top 5 truncated
        for msg, count in msg_counts.head(5).items():
            truncated = msg[:120] + "..." if len(str(msg)) > 120 else msg
            st.caption(f"`{count}x` {truncated}")
        if len(msg_counts) > 5:
            with st.expander(f"All {len(msg_counts)} distinct error messages"):
                for msg, count in msg_counts.items():
                    truncated = msg[:200] + "..." if len(str(msg)) > 200 else msg
                    st.caption(f"`{count}x` {truncated}")

    if not warnings.empty:
        messages = warnings["data"].apply(lambda d: d.get("message", "unknown") if isinstance(d, dict) else "unknown")
        msg_counts = messages.value_counts()
        for msg, count in msg_counts.head(3).items():
            truncated = msg[:120] + "..." if len(str(msg)) > 120 else msg
            st.caption(f"`{count}x` {truncated}")

    # Error timeline
    all_errors = pd.concat([errors, warnings], ignore_index=True)
    if len(all_errors) > 1:
        all_errors = bin_by_time(all_errors, "1h")
        hourly = all_errors.groupby(["time_bin", "event_type"]).size().reset_index(name="count")

        fig = go.Figure()
        for etype, color in [("error", COLORS["error"]), ("warning", COLORS["warning"])]:
            data = hourly[hourly["event_type"] == etype]
            if not data.empty:
                fig.add_trace(
                    go.Bar(
                        x=data["time_bin"],
                        y=data["count"],
                        name=etype.title(),
                        marker_color=color,
                        hovertemplate=f"{etype}: %{{y}}<extra></extra>",
                    )
                )
        fig.update_layout(
            title="Gateway Errors & Warnings (hourly)",
            height=250,
            barmode="stack",
            xaxis_title="Time",
            yaxis_title="Count",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        apply_plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")


# ── Billing Sync Drift ────────────────────────────────────────────────────────


def _billing_drift(df: pd.DataFrame):
    drift = get_events(df, "billing_sync_drift")
    if drift.empty:
        st.caption("No billing sync drift events (webhooks working correctly)")
        return

    st.metric("Drift Events", format_number(len(drift)))
    for _, row in drift.iterrows():
        data = row.get("data", {})
        if isinstance(data, dict):
            user = data.get("user_id", "?")
            drift_info = data.get("drift", data.get("drifted", "?"))
            st.caption(f"User `{user[:8]}...`: {drift_info}")


# ── Cache Evictions ───────────────────────────────────────────────────────────


def _cache_evictions(df: pd.DataFrame):
    evictions = get_events(df, "eviction_triggered")
    if evictions.empty:
        st.caption("No cache eviction events")
        return

    st.metric("Evictions", format_number(len(evictions)))
    if len(evictions) > 1:
        evictions = bin_by_time(evictions, "1h")
        hourly = evictions.groupby("time_bin").size().reset_index(name="count")
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=hourly["time_bin"],
                y=hourly["count"],
                marker_color=COLORS["warning"],
                hovertemplate="%{y} evictions<extra></extra>",
            )
        )
        fig.update_layout(title="Cache Evictions (hourly)", height=200, xaxis_title="Time", yaxis_title="Count")
        apply_plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")


# ── API Rate Limits ───────────────────────────────────────────────────────────


def _rate_limit_timeline(df: pd.DataFrame) -> go.Figure | None:
    rate_limits = get_events(df, "api_rate_limit")
    if rate_limits.empty:
        return None

    rate_limits = rate_limits.copy()
    rate_limits["api_name"] = rate_limits["data"].apply(
        lambda d: d.get("api_name", "unknown") if isinstance(d, dict) else "unknown"
    )
    rate_limits = bin_by_time(rate_limits, "1h")

    api_colors = {"gemini": COLORS["accent_blue"]}

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
                hovertemplate=f"{api_name}: %{{y}}<extra></extra>",
            )
        )

    fig.update_layout(
        title="API Rate Limits (hourly)",
        height=280,
        barmode="stack",
        xaxis_title="Time",
        yaxis_title="429 Responses",
    )
    apply_plotly_theme(fig)
    return fig


# ── Retries & DLQ ─────────────────────────────────────────────────────────────


def _retry_timeline(df: pd.DataFrame) -> go.Figure | None:
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
            marker=dict(size=5),
            fill="tozeroy",
            fillcolor="rgba(210, 153, 34, 0.15)",
            hovertemplate="%{y} requeued<extra></extra>",
        )
    )
    fig.update_layout(title="Job Requeues (hourly)", height=280, xaxis_title="Time", yaxis_title="Requeued Jobs")
    apply_plotly_theme(fig)
    return fig


def _dlq_timeline(df: pd.DataFrame) -> go.Figure | None:
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
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(248, 81, 73, 0.15)",
            hovertemplate="%{y} to DLQ<extra></extra>",
        )
    )
    fig.update_layout(title="Dead Letter Queue (hourly)", height=280, xaxis_title="Time", yaxis_title="DLQ Jobs")
    apply_plotly_theme(fig)
    return fig


def _incomplete_jobs_chart(df: pd.DataFrame) -> go.Figure | None:
    queued = get_events(df, "synthesis_queued").copy()
    completed = get_events(df, "synthesis_complete")
    errored = get_events(df, "synthesis_error")

    if queued.empty:
        return None

    finished_hashes = set(completed["variant_hash"].dropna()) | set(errored["variant_hash"].dropna())
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
            marker=dict(size=5),
            fill="tozeroy",
            fillcolor="rgba(110, 118, 129, 0.15)",
            hovertemplate="%{y} incomplete<extra></extra>",
        )
    )
    fig.update_layout(title="Incomplete Jobs (hourly)", height=280, xaxis_title="Time", yaxis_title="Jobs")
    apply_plotly_theme(fig)
    return fig


def _reliability_by_queue(df: pd.DataFrame):
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
    st.dataframe(display_df, hide_index=True, width="stretch")


# ── Main Render ───────────────────────────────────────────────────────────────


def render(df: pd.DataFrame):
    """Render the Reliability tab."""
    section_header("Summary", "Reliability metrics")
    _summary_stats(df)

    st.divider()

    # WebSocket sessions
    section_header("WebSocket Sessions", "Connection lifecycle")
    _websocket_sessions(df)

    st.divider()

    # Gateway errors
    section_header("Gateway Errors", "Internal error and warning events")
    _gateway_errors(df)

    st.divider()

    # Stripe webhooks
    section_header("Stripe Webhooks", "Webhook processing health")
    _webhook_stats(df)

    st.divider()

    # API rate limits
    section_header("API Rate Limits", "429 responses from external APIs")
    fig = _rate_limit_timeline(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No rate limit events")

    st.divider()

    # Billing sync drift
    section_header("Billing Sync", "Subscription drift detection")
    _billing_drift(df)

    st.divider()

    # Cache evictions
    section_header("Cache Evictions", "Audio cache LRU evictions")
    _cache_evictions(df)

    st.divider()

    # By queue type
    section_header("By Queue Type")
    _reliability_by_queue(df)

    st.divider()

    # Job processing charts
    section_header("Job Processing")
    col1, col2 = st.columns(2)
    with col1:
        fig = _retry_timeline(df)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No retry events")
    with col2:
        fig = _dlq_timeline(df)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No DLQ events")

    fig = _incomplete_jobs_chart(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No incomplete jobs")
