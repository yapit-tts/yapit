"""TTS tab - Text-to-speech synthesis performance metrics."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard.components import (
    empty_state,
    format_duration,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, calculate_rate, get_events
from dashboard.theme import COLORS, apply_plotly_theme, get_model_color


def _worker_stats_table(df: pd.DataFrame):
    """Display per-worker performance table."""
    complete = get_events(df, "synthesis_complete")
    errors = get_events(df, "synthesis_error")

    if complete.empty:
        st.caption("No synthesis data for worker breakdown")
        return

    # Combine for worker stats
    all_events = pd.concat([complete, errors], ignore_index=True)
    if "worker_id" not in all_events.columns or all_events["worker_id"].isna().all():
        st.caption("No worker_id data available")
        return

    workers = (
        all_events.groupby("worker_id")
        .agg(
            jobs=("event_type", "count"),
            completed=("event_type", lambda x: (x == "synthesis_complete").sum()),
            errors=("event_type", lambda x: (x == "synthesis_error").sum()),
            p50_latency=("worker_latency_ms", lambda x: x.quantile(0.5)),
            p95_latency=("worker_latency_ms", lambda x: x.quantile(0.95)),
            avg_queue_wait=("queue_wait_ms", "mean"),
        )
        .reset_index()
    )

    workers["error_rate"] = workers.apply(lambda r: r["errors"] / r["jobs"] * 100 if r["jobs"] > 0 else 0, axis=1)

    # Format for display
    display_df = pd.DataFrame(
        {
            "Worker": workers["worker_id"],
            "Jobs": workers["jobs"],
            "Completed": workers["completed"],
            "Errors": workers["errors"],
            "Error %": workers["error_rate"].apply(lambda x: f"{x:.1f}%"),
            "P50 Latency": workers["p50_latency"].apply(format_duration),
            "P95 Latency": workers["p95_latency"].apply(format_duration),
            "Avg Queue Wait": workers["avg_queue_wait"].apply(format_duration),
        }
    )

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def _latency_stats_table(df: pd.DataFrame):
    """Display latency statistics by model."""
    complete = get_events(df, "synthesis_complete")
    if complete.empty:
        st.caption("No latency data")
        return

    models = complete["model_slug"].dropna().unique()
    rows = []

    for model in sorted(models):
        model_data = complete[complete["model_slug"] == model]
        worker = model_data["worker_latency_ms"].dropna()
        queue = model_data["queue_wait_ms"].dropna()
        total = model_data["total_latency_ms"].dropna()

        if worker.empty:
            continue

        rows.append(
            {
                "Model": model,
                "Count": len(model_data),
                "P50 Worker": format_duration(worker.quantile(0.5)),
                "P95 Worker": format_duration(worker.quantile(0.95)),
                "P50 Queue": format_duration(queue.quantile(0.5)) if not queue.empty else "-",
                "P95 Queue": format_duration(queue.quantile(0.95)) if not queue.empty else "-",
                "P50 Total": format_duration(total.quantile(0.5)) if not total.empty else "-",
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _cache_stats(df: pd.DataFrame):
    """Display audio cache statistics."""
    hits = len(get_events(df, "cache_hit"))
    misses = len(get_events(df, "synthesis_queued"))
    rate = calculate_rate(hits, misses)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Cache Hits", format_number(hits))
    with col2:
        st.metric("Cache Misses", format_number(misses))
    with col3:
        st.metric("Hit Rate", format_percent(rate))


def _queue_depth_chart(df: pd.DataFrame) -> go.Figure | None:
    """Queue depth over time by model."""
    queued = get_events(df, "synthesis_queued")
    if queued.empty or "queue_depth" not in queued.columns:
        return None

    queued = queued.dropna(subset=["queue_depth"])
    if queued.empty:
        return None

    fig = go.Figure()

    for model in queued["model_slug"].dropna().unique():
        model_data = queued[queued["model_slug"] == model]
        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["queue_depth"],
                mode="markers",
                name=model,
                marker=dict(size=6, color=get_model_color(model)),
                hovertemplate=f"<b>{model}</b><br>Depth: %{{y}}<br>%{{x}}<extra></extra>",
            )
        )

    fig.update_layout(
        title="Queue Depth at Enqueue Time",
        height=300,
        xaxis_title="Time",
        yaxis_title="Queue Depth",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _queue_wait_histogram(df: pd.DataFrame) -> go.Figure | None:
    """Queue wait time distribution."""
    complete = get_events(df, "synthesis_complete")
    if complete.empty or "queue_wait_ms" not in complete.columns:
        return None

    queue_wait = complete["queue_wait_ms"].dropna()
    if queue_wait.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=queue_wait,
            nbinsx=30,
            marker=dict(color=COLORS["accent_blue"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Wait: %{x:.0f}ms<br>Count: %{y}<extra></extra>",
        )
    )

    median = queue_wait.median()
    fig.add_vline(
        x=median,
        line_dash="dash",
        line_color=COLORS["accent_teal"],
        annotation_text=f"Median: {format_duration(median)}",
        annotation_position="top right",
    )

    fig.update_layout(
        title="Queue Wait Time Distribution",
        height=300,
        xaxis_title="Queue Wait (ms)",
        yaxis_title="Count",
    )
    apply_plotly_theme(fig)
    return fig


def _latency_scatter(df: pd.DataFrame) -> go.Figure | None:
    """Worker latency scatter plot by model."""
    complete = get_events(df, "synthesis_complete")
    complete = complete.dropna(subset=["worker_latency_ms"])
    if complete.empty:
        return None

    fig = go.Figure()

    for model in sorted(complete["model_slug"].dropna().unique()):
        model_data = complete[complete["model_slug"] == model]
        color = get_model_color(model)

        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["worker_latency_ms"],
                mode="markers",
                name=model,
                marker=dict(
                    size=8,
                    color=color,
                    opacity=0.7,
                ),
                hovertemplate=f"<b>{model}</b><br>%{{y:.0f}}ms<br>%{{x}}<extra></extra>",
            )
        )

    fig.update_layout(
        title="Worker Latency Over Time (by Model)",
        height=350,
        xaxis_title="Time",
        yaxis_title="Worker Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _realtime_ratio_chart(df: pd.DataFrame) -> go.Figure | None:
    """Realtime ratio scatter + histogram by model."""
    complete = get_events(df, "synthesis_complete")
    complete = complete.dropna(subset=["worker_latency_ms", "audio_duration_ms"])
    complete = complete[complete["audio_duration_ms"] > 0]
    if complete.empty:
        return None

    complete = complete.copy()
    complete["ratio"] = complete["worker_latency_ms"] / complete["audio_duration_ms"]

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.6, 0.4],
        subplot_titles=["Realtime Ratio Over Time", "Distribution"],
    )

    # Scatter by model
    for model in sorted(complete["model_slug"].dropna().unique()):
        model_data = complete[complete["model_slug"] == model]
        color = get_model_color(model)

        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["ratio"],
                mode="markers",
                name=model,
                marker=dict(size=7, color=color, opacity=0.7),
                hovertemplate=f"<b>{model}</b><br>%{{y:.2f}}x<br>%{{x}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # Histogram (all models combined)
    fig.add_trace(
        go.Histogram(
            x=complete["ratio"],
            nbinsx=20,
            marker=dict(color=COLORS["accent_purple"], line=dict(width=1, color=COLORS["border"])),
            showlegend=False,
            hovertemplate="Ratio: %{x:.2f}<br>Count: %{y}<extra></extra>",
        ),
        row=1,
        col=2,
    )

    # Real-time threshold line
    fig.add_hline(y=1.0, line_dash="dash", line_color=COLORS["error"], row=1, col=1)
    fig.add_vline(
        x=1.0,
        line_dash="dash",
        line_color=COLORS["error"],
        annotation_text="Real-time",
        annotation_position="top right",
        row=1,
        col=2,
    )

    median = complete["ratio"].median()
    fig.add_vline(
        x=median,
        line_dash="solid",
        line_color=COLORS["accent_teal"],
        annotation_text=f"Median: {median:.2f}x",
        annotation_position="top left",
        row=1,
        col=2,
    )

    fig.update_layout(
        title="Synthesis Speed (ratio < 1 = faster than real-time)",
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_xaxes(title_text="Ratio", row=1, col=2)
    fig.update_yaxes(title_text="Ratio (worker / audio)", row=1, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=2)
    apply_plotly_theme(fig)
    return fig


def _text_length_vs_latency(df: pd.DataFrame) -> go.Figure | None:
    """Text length vs latency correlation."""
    complete = get_events(df, "synthesis_complete")
    complete = complete.dropna(subset=["worker_latency_ms", "text_length"])
    if complete.empty:
        return None

    fig = go.Figure()

    for model in sorted(complete["model_slug"].dropna().unique()):
        model_data = complete[complete["model_slug"] == model]
        color = get_model_color(model)

        fig.add_trace(
            go.Scatter(
                x=model_data["text_length"],
                y=model_data["worker_latency_ms"],
                mode="markers",
                name=model,
                marker=dict(size=7, color=color, opacity=0.6),
                hovertemplate=f"<b>{model}</b><br>%{{x}} chars<br>%{{y:.0f}}ms<extra></extra>",
            )
        )

    fig.update_layout(
        title="Text Length vs Latency",
        height=350,
        xaxis_title="Text Length (chars)",
        yaxis_title="Worker Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _cps_chart(df: pd.DataFrame) -> go.Figure | None:
    """Characters per second scatter + histogram by model."""
    complete = get_events(df, "synthesis_complete")
    complete = complete.dropna(subset=["text_length", "audio_duration_ms"])
    complete = complete[complete["audio_duration_ms"] > 0]
    if complete.empty:
        return None

    complete = complete.copy()
    complete["cps"] = complete["text_length"] * 1000 / complete["audio_duration_ms"]

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.6, 0.4],
        subplot_titles=["CPS Over Time", "Distribution"],
    )

    # Scatter by model
    for model in sorted(complete["model_slug"].dropna().unique()):
        model_data = complete[complete["model_slug"] == model]
        color = get_model_color(model)

        fig.add_trace(
            go.Scatter(
                x=model_data["local_time"],
                y=model_data["cps"],
                mode="markers",
                name=model,
                marker=dict(size=7, color=color, opacity=0.7),
                hovertemplate=f"<b>{model}</b><br>%{{y:.1f}} chars/s<br>%{{x}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # Histogram (all models combined)
    fig.add_trace(
        go.Histogram(
            x=complete["cps"],
            nbinsx=25,
            marker=dict(color=COLORS["accent_teal"], line=dict(width=1, color=COLORS["border"])),
            showlegend=False,
            hovertemplate="CPS: %{x:.1f}<br>Count: %{y}<extra></extra>",
        ),
        row=1,
        col=2,
    )

    # Hardcoded constant reference line (14 CPS used in estimates)
    fig.add_hline(
        y=14,
        line_dash="dash",
        line_color=COLORS["accent_yellow"],
        annotation_text="Est: 14",
        annotation_position="right",
        row=1,
        col=1,
    )
    fig.add_vline(
        x=14,
        line_dash="dash",
        line_color=COLORS["accent_yellow"],
        annotation_text="Est: 14",
        annotation_position="top right",
        row=1,
        col=2,
    )

    median = complete["cps"].median()
    fig.add_vline(
        x=median,
        line_dash="solid",
        line_color=COLORS["accent_purple"],
        annotation_text=f"Median: {median:.1f}",
        annotation_position="top left",
        row=1,
        col=2,
    )

    fig.update_layout(
        title="Characters Per Second (text_length × 1000 / audio_duration_ms)",
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_xaxes(title_text="CPS", row=1, col=2)
    fig.update_yaxes(title_text="Chars/Second", row=1, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=2)
    apply_plotly_theme(fig)
    return fig


def _latency_breakdown_chart(df: pd.DataFrame) -> go.Figure | None:
    """Stacked bar: queue wait vs worker time."""
    complete = get_events(df, "synthesis_complete")
    complete = complete.dropna(subset=["worker_latency_ms"])
    if complete.empty:
        return None

    complete = bin_by_time(complete, "10min")
    if "queue_wait_ms" not in complete.columns:
        return None

    grouped = (
        complete.groupby("time_bin")
        .agg(
            queue_wait=("queue_wait_ms", "mean"),
            worker_time=("worker_latency_ms", "mean"),
            count=("variant_hash", "count"),
        )
        .reset_index()
    )

    if grouped.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=grouped["time_bin"],
            y=grouped["queue_wait"],
            name="Queue Wait",
            marker_color=COLORS["accent_yellow"],
            hovertemplate="Queue: %{y:.0f}ms<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=grouped["time_bin"],
            y=grouped["worker_time"],
            name="Worker Time",
            marker_color=COLORS["accent_teal"],
            hovertemplate="Worker: %{y:.0f}ms<extra></extra>",
        )
    )

    fig.update_layout(
        title="Latency Breakdown (10-min averages)",
        barmode="stack",
        height=300,
        xaxis_title="Time",
        yaxis_title="Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _billing_section(df: pd.DataFrame):
    """Billing consumer health: reconciliation and processing time."""
    billing = get_events(df, "billing_processed")
    synthesis = get_events(df, "synthesis_complete")

    if billing.empty and synthesis.empty:
        section_header("Billing Consumer", "Cold path health")
        st.caption("No billing data")
        return

    # Reconciliation: synthesis events vs billed events
    synthesized_count = len(synthesis)
    billed_count = int(billing["data"].apply(lambda d: d.get("events_count", 0) if isinstance(d, dict) else 0).sum())
    delta = synthesized_count - billed_count

    if delta <= 5:
        delta_color = COLORS["success"]
    elif delta <= 50:
        delta_color = COLORS["warning"]
    else:
        delta_color = COLORS["error"]

    section_header("Billing Consumer", "Cold path health")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Events Billed", format_number(billed_count))
    with col2:
        durations = billing["duration_ms"].dropna()
        if not durations.empty:
            st.metric(
                "Batch Processing",
                f"P50 {format_duration(durations.median())} / P95 {format_duration(durations.quantile(0.95))}",
            )
        else:
            st.metric("Batch Processing", "-")
    with col3:
        st.markdown(
            f"**Reconciliation Delta**"
            f"<br><span style='font-size:1.8em;color:{delta_color}'>{delta:+d}</span>"
            f"<br><span style='color:{COLORS['text_muted']};font-size:0.85em'>"
            f"{format_number(synthesized_count)} synthesized − {format_number(billed_count)} billed</span>",
            unsafe_allow_html=True,
        )

    # Processing time scatter
    if not billing.empty:
        fig = _billing_processing_chart(billing)
        if fig:
            st.plotly_chart(fig, use_container_width=True)


def _billing_processing_chart(billing: pd.DataFrame) -> go.Figure | None:
    """Billing batch processing time over time."""
    billing = billing.dropna(subset=["duration_ms"])
    if billing.empty:
        return None

    batch_sizes = billing["data"].apply(lambda d: d.get("events_count", 1) if isinstance(d, dict) else 1)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=billing["local_time"],
            y=billing["duration_ms"],
            mode="markers",
            marker=dict(
                size=batch_sizes.clip(upper=20).apply(lambda s: max(5, s)),
                color=COLORS["accent_teal"],
                opacity=0.7,
            ),
            customdata=batch_sizes,
            hovertemplate="%{y:.0f}ms (%{customdata} events)<extra></extra>",
        )
    )

    fig.update_layout(
        title="Billing Batch Processing Time",
        height=250,
        xaxis_title="Time",
        yaxis_title="Duration (ms)",
    )
    apply_plotly_theme(fig)
    return fig


def render(df: pd.DataFrame):
    """Render the TTS tab."""
    if df.empty:
        empty_state("No TTS data available")
        return

    # Cache stats row
    section_header("Audio Cache", "Synthesis cache performance")
    _cache_stats(df)

    st.divider()

    # Latency stats by model
    section_header("Latency by Model", "Worker and queue latencies")
    _latency_stats_table(df)

    st.divider()

    # Per-worker breakdown
    section_header("Per-Worker Performance", "Individual worker statistics")
    _worker_stats_table(df)

    st.divider()

    # Charts
    section_header("Charts")

    # Row 1: Latency scatter
    fig = _latency_scatter(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Row 2: Realtime ratio
    fig = _realtime_ratio_chart(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Row 3: Characters per second
    fig = _cps_chart(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Row 4: Queue depth + wait distribution
    col1, col2 = st.columns(2)
    with col1:
        fig = _queue_depth_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No queue depth data")

    with col2:
        fig = _queue_wait_histogram(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No queue wait data")

    # Row 5: Latency breakdown + text length correlation
    col1, col2 = st.columns(2)
    with col1:
        fig = _latency_breakdown_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No latency breakdown data")

    with col2:
        fig = _text_length_vs_latency(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No text length data")

    # Billing consumer health
    st.divider()
    _billing_section(df)
