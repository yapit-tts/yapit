"""Overview tab — executive summary with KPIs, sparklines, and long-range trends."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_cost,
    format_duration,
    format_number,
    format_percent,
    kpi_row,
    section_header,
)
from dashboard.data import calculate_gemini_cost, calculate_rate, get_events, get_events_multi
from dashboard.theme import COLORS, apply_plotly_theme


def _get_kpi_data(df: pd.DataFrame) -> list[dict]:
    synthesis_complete = get_events(df, "synthesis_complete")
    audio_min = synthesis_complete["audio_duration_ms"].sum() / 60000

    synthesis_queued = get_events(df, "synthesis_queued")
    cache_hits = get_events(df, "cache_hit")
    total_requests = len(synthesis_queued) + len(cache_hits)
    cache_rate = (len(cache_hits) / total_requests * 100) if total_requests > 0 else 0

    synthesis_errors = get_events(df, "synthesis_error")
    total_synthesis = len(synthesis_complete) + len(synthesis_errors)
    error_rate = (len(synthesis_errors) / total_synthesis * 100) if total_synthesis > 0 else 0

    avg_latency = synthesis_complete["worker_latency_ms"].mean() if not synthesis_complete.empty else 0
    gemini_cost = calculate_gemini_cost(get_events(df, "page_extraction_complete"))

    return [
        {"label": "Audio Generated", "value": f"{audio_min:.1f} min", "help": "Total audio duration synthesized"},
        {
            "label": "Blocks Synthesized",
            "value": format_number(len(synthesis_queued)),
            "help": "Cache misses requiring synthesis",
        },
        {"label": "Cache Hit Rate", "value": format_percent(cache_rate), "help": "Blocks served from cache"},
        {"label": "Error Rate", "value": format_percent(error_rate), "help": "Synthesis error rate"},
        {"label": "Avg Latency", "value": format_duration(avg_latency), "help": "Average worker processing time"},
        {"label": "Gemini Cost", "value": format_cost(gemini_cost), "help": "Estimated Gemini API cost"},
    ]


def _volume_sparkline(df: pd.DataFrame) -> go.Figure | None:
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    events = events.copy()
    events["hour"] = events["local_time"].dt.floor("h")
    hourly = events.groupby("hour").size().reset_index(name="count")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["hour"],
            y=hourly["count"],
            mode="lines",
            line=dict(color=COLORS["accent_teal"], width=2),
            fill="tozeroy",
            fillcolor="rgba(57, 217, 138, 0.15)",
            hovertemplate="%{y} requests<extra></extra>",
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["text_primary"]},
        height=140,
        margin=dict(l=0, r=0, t=4, b=30),
        xaxis=dict(showgrid=False, title=None, gridcolor="rgba(48,54,61,0.5)"),
        yaxis=dict(showgrid=True, title=None, gridcolor=COLORS["border"]),
        showlegend=False,
    )
    return fig


def _cache_summary(df: pd.DataFrame):
    audio_hits = len(get_events(df, "cache_hit"))
    audio_misses = len(get_events(df, "synthesis_queued"))
    audio_rate = calculate_rate(audio_hits, audio_misses)

    doc_hit_count = len(get_events(df, "document_cache_hit"))

    extraction_hits = len(get_events(df, "extraction_cache_hit"))
    extraction_misses = len(get_events(df, "page_extraction_complete"))
    extraction_rate = calculate_rate(extraction_hits, extraction_misses)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Audio Cache**")
        st.markdown(f"### {format_percent(audio_rate)}")
        st.caption(f"{format_number(audio_hits)} hits / {format_number(audio_misses)} misses")
    with col2:
        st.markdown("**Document Cache**")
        st.markdown(f"### {format_number(doc_hit_count)} hits")
        st.caption("URL/upload deduplication")
    with col3:
        st.markdown("**Extraction Cache**")
        st.markdown(f"### {format_percent(extraction_rate)}")
        st.caption(f"{format_number(extraction_hits)} hits / {format_number(extraction_misses)} processed")


def _event_breakdown(df: pd.DataFrame):
    counts = df["event_type"].value_counts().head(15)
    if counts.empty:
        return

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=counts.index,
            x=counts.values,
            orientation="h",
            marker=dict(color=COLORS["accent_blue"], line=dict(width=0)),
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        )
    )
    apply_plotly_theme(fig)
    fig.update_layout(
        title="",
        height=max(200, len(counts) * 26),
        margin=dict(l=0, r=10, t=0, b=0),
        xaxis=dict(title=None, showgrid=True, gridcolor=COLORS["border"]),
        yaxis=dict(title=None, autorange="reversed"),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


def _queue_health(df: pd.DataFrame):
    tts_queued = get_events(df, "synthesis_queued")
    detection_queued = get_events(df, "detection_queued")

    col1, col2 = st.columns(2)
    with col1:
        if not tts_queued.empty:
            depths = tts_queued["queue_depth"].dropna()
            st.markdown("**TTS Queue**")
            if not depths.empty:
                st.markdown(f"Avg depth: **{depths.mean():.1f}** | Max: **{depths.max():.0f}**")
            else:
                st.caption("No depth data")
        else:
            st.caption("No TTS queue data")
    with col2:
        if not detection_queued.empty:
            depths = detection_queued["queue_depth"].dropna()
            st.markdown("**Detection Queue**")
            if not depths.empty:
                st.markdown(f"Avg depth: **{depths.mean():.1f}** | Max: **{depths.max():.0f}**")
            else:
                st.caption("No depth data")
        else:
            st.caption("No detection queue data")


# ── Long-Range Trends (from daily aggregates) ────────────────────────────────


def _trends_volume(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily event volume from aggregates."""
    if daily_df.empty:
        return None

    # Sum event counts per day across all types
    daily_total = daily_df.groupby("local_date")["event_count"].sum().reset_index()
    if daily_total.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily_total["local_date"],
            y=daily_total["event_count"],
            mode="lines",
            line=dict(color=COLORS["accent_teal"], width=2),
            fill="tozeroy",
            fillcolor="rgba(57, 217, 138, 0.1)",
            hovertemplate="%{x|%b %d}: %{y:,.0f} events<extra></extra>",
        )
    )
    fig.update_layout(title="Daily Event Volume", height=220, xaxis_title=None, yaxis_title="Events")
    apply_plotly_theme(fig)
    return fig


def _trends_latency(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily P50/P95 latency for synthesis_complete."""
    synth = daily_df[daily_df["event_type"] == "synthesis_complete"].copy()
    if synth.empty:
        return None

    # Aggregate across models per day
    daily = (
        synth.groupby("local_date")
        .agg(
            p50=("p50_total_latency_ms", "mean"),
            p95=("p95_total_latency_ms", "mean"),
        )
        .reset_index()
    )

    if daily.empty or daily["p50"].isna().all():
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily["local_date"],
            y=daily["p50"],
            mode="lines",
            name="P50",
            line=dict(color=COLORS["accent_teal"], width=2),
            hovertemplate="P50: %{y:.0f}ms<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily["local_date"],
            y=daily["p95"],
            mode="lines",
            name="P95",
            line=dict(color=COLORS["accent_coral"], width=2),
            hovertemplate="P95: %{y:.0f}ms<extra></extra>",
        )
    )
    fig.update_layout(
        title="Daily Synthesis Latency (P50/P95)",
        height=220,
        xaxis_title=None,
        yaxis_title="Latency (ms)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _trends_users(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily unique users from aggregates."""
    if daily_df.empty or "unique_users" not in daily_df.columns:
        return None

    daily_users = daily_df.groupby("local_date")["unique_users"].max().reset_index()
    if daily_users.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily_users["local_date"],
            y=daily_users["unique_users"],
            mode="lines+markers",
            line=dict(color=COLORS["accent_cyan"], width=2),
            marker=dict(size=4),
            fill="tozeroy",
            fillcolor="rgba(86, 212, 221, 0.1)",
            hovertemplate="%{x|%b %d}: %{y} users<extra></extra>",
        )
    )
    fig.update_layout(title="Daily Unique Users", height=220, xaxis_title=None, yaxis_title="Users")
    apply_plotly_theme(fig)
    return fig


def _trends_cache(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily cache hit rate from aggregates.

    cache_hit and synthesis_queued are separate event types in the aggregates.
    Hit rate = cache_hit count / (cache_hit count + synthesis_queued count).
    """
    hits_df = daily_df[daily_df["event_type"] == "cache_hit"].copy()
    misses_df = daily_df[daily_df["event_type"] == "synthesis_queued"].copy()

    if hits_df.empty and misses_df.empty:
        return None

    hits_daily = hits_df.groupby("local_date")["event_count"].sum().reset_index(name="hits")
    misses_daily = misses_df.groupby("local_date")["event_count"].sum().reset_index(name="misses")

    daily = hits_daily.merge(misses_daily, on="local_date", how="outer").fillna(0)
    daily["total"] = daily["hits"] + daily["misses"]
    daily["rate"] = (daily["hits"] / daily["total"].replace(0, pd.NA) * 100).fillna(0)

    if daily.empty or daily["total"].sum() == 0:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily["local_date"],
            y=daily["rate"],
            mode="lines+markers",
            line=dict(color=COLORS["accent_purple"], width=2),
            marker=dict(size=4),
            hovertemplate="%{x|%b %d}: %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(title="Daily Audio Cache Hit Rate", height=220, xaxis_title=None, yaxis_title="Hit Rate %")
    apply_plotly_theme(fig)
    return fig


def _trends_audio(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily audio minutes generated."""
    synth = daily_df[daily_df["event_type"] == "synthesis_complete"].copy()
    if synth.empty or "total_audio_ms" not in synth.columns:
        return None

    daily = synth.groupby("local_date")["total_audio_ms"].sum().reset_index()
    daily["audio_min"] = daily["total_audio_ms"] / 60000

    if daily.empty or daily["audio_min"].sum() == 0:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=daily["local_date"],
            y=daily["audio_min"],
            marker_color=COLORS["accent_blue"],
            hovertemplate="%{x|%b %d}: %{y:.1f} min<extra></extra>",
        )
    )
    fig.update_layout(title="Daily Audio Generated", height=220, xaxis_title=None, yaxis_title="Minutes")
    apply_plotly_theme(fig)
    return fig


def _trends_tokens(daily_df: pd.DataFrame) -> go.Figure | None:
    """Daily token consumption (input/output/thinking/cached) from aggregates."""
    ext = daily_df[daily_df["event_type"] == "page_extraction_complete"].copy()
    if ext.empty:
        return None

    token_cols = ["total_prompt_tokens", "total_candidates_tokens", "total_thoughts_tokens", "total_cached_tokens"]
    if not all(c in ext.columns for c in token_cols):
        return None

    daily = ext.groupby("local_date")[token_cols].sum().reset_index()
    if daily[token_cols].sum().sum() == 0:
        return None

    fig = go.Figure()
    for col, name, color in [
        ("total_prompt_tokens", "Input", "rgba(88, 166, 255, 0.7)"),
        ("total_candidates_tokens", "Output", "rgba(57, 217, 138, 0.7)"),
        ("total_thoughts_tokens", "Thinking", "rgba(163, 113, 247, 0.7)"),
        ("total_cached_tokens", "Cached", "rgba(86, 212, 221, 0.7)"),
    ]:
        if col in daily.columns and daily[col].sum() > 0:
            fig.add_trace(
                go.Scatter(
                    x=daily["local_date"],
                    y=daily[col],
                    mode="lines",
                    name=name,
                    line=dict(width=0),
                    fill="tonexty",
                    fillcolor=color,
                    stackgroup="one",
                    hovertemplate=f"{name}: %{{y:,.0f}}<extra></extra>",
                )
            )

    fig.update_layout(
        title="Daily Token Consumption",
        height=220,
        xaxis_title=None,
        yaxis_title="Tokens",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


# ── Main Render ───────────────────────────────────────────────────────────────


def render(df: pd.DataFrame, daily_df: pd.DataFrame | None = None):
    """Render the overview tab."""
    if df.empty:
        empty_state("No data available for the selected time range")
        return

    # KPI row
    section_header("Key Metrics", "Executive summary for selected range")
    kpis = _get_kpi_data(df)
    kpi_row(kpis, cols=6)

    st.divider()

    # Volume sparkline
    st.markdown("**Request Volume Over Time**")
    fig = _volume_sparkline(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No request data")

    st.divider()

    # Cache + queue health
    col1, col2 = st.columns(2)
    with col1:
        section_header("Cache Performance")
        _cache_summary(df)
    with col2:
        section_header("Queue Health")
        _queue_health(df)

    st.divider()

    # Event breakdown
    section_header("Event Breakdown", "Top event types by count")
    _event_breakdown(df)

    # ── Long-Range Trends ──
    if daily_df is not None and not daily_df.empty:
        st.divider()
        section_header("Trends", "All-time daily aggregates (independent of date range filter)")

        col1, col2 = st.columns(2)
        with col1:
            fig = _trends_volume(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")
        with col2:
            fig = _trends_latency(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")

        col1, col2 = st.columns(2)
        with col1:
            fig = _trends_users(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")
        with col2:
            fig = _trends_cache(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")

        col1, col2 = st.columns(2)
        with col1:
            fig = _trends_audio(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")
        with col2:
            fig = _trends_tokens(daily_df)
            if fig:
                st.plotly_chart(fig, width="stretch")
