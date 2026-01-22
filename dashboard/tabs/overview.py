"""Overview tab - Executive summary with KPIs and sparklines."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    delta_str,
    empty_state,
    format_cost,
    format_duration,
    format_number,
    format_percent,
    kpi_row,
    section_header,
)
from dashboard.data import calculate_rate, get_events, get_events_multi
from dashboard.theme import COLORS, apply_plotly_theme

# Gemini 3 Flash Preview pricing
GEMINI_INPUT_COST_PER_M = 0.50  # $/M tokens
GEMINI_OUTPUT_COST_PER_M = 3.00  # $/M tokens (thoughts count as output)


def _calculate_gemini_cost(df: pd.DataFrame) -> float:
    """Calculate total Gemini API cost from extraction events."""
    extraction = get_events(df, "page_extraction_complete")
    if extraction.empty:
        return 0.0

    prompt_tokens = extraction["prompt_token_count"].sum()
    # Output = candidates + thoughts
    output_tokens = (
        extraction["candidates_token_count"].fillna(0).sum() + extraction["thoughts_token_count"].fillna(0).sum()
    )

    input_cost = (prompt_tokens / 1_000_000) * GEMINI_INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * GEMINI_OUTPUT_COST_PER_M

    return input_cost + output_cost


def _get_kpi_data(df: pd.DataFrame, comparison: pd.DataFrame | None = None) -> list[dict]:
    """Calculate KPI metrics."""
    # Audio generated
    synthesis_complete = get_events(df, "synthesis_complete")
    audio_ms = synthesis_complete["audio_duration_ms"].sum()
    audio_min = audio_ms / 60000

    # Blocks synthesized (actual synthesis work, not cache hits)
    synthesis_queued = get_events(df, "synthesis_queued")
    cache_hits = get_events(df, "cache_hit")
    blocks_synthesized = len(synthesis_queued)

    # Cache hit rate: cache_hits / total_requests
    total_requests = len(synthesis_queued) + len(cache_hits)
    cache_rate = (len(cache_hits) / total_requests * 100) if total_requests > 0 else 0

    # Error rate
    synthesis_errors = get_events(df, "synthesis_error")
    total_synthesis = len(synthesis_complete) + len(synthesis_errors)
    error_rate = (len(synthesis_errors) / total_synthesis * 100) if total_synthesis > 0 else 0

    # Average latency
    avg_latency = synthesis_complete["worker_latency_ms"].mean() if not synthesis_complete.empty else 0

    # Gemini cost
    gemini_cost = _calculate_gemini_cost(df)

    # Calculate deltas if comparison data provided
    deltas = {}
    if comparison is not None and not comparison.empty:
        comp_synthesis = get_events(comparison, "synthesis_complete")
        comp_audio_min = comp_synthesis["audio_duration_ms"].sum() / 60000
        if comp_audio_min > 0:
            deltas["audio"] = delta_str(audio_min, comp_audio_min)

        comp_synthesized = len(get_events(comparison, "synthesis_queued"))
        if comp_synthesized > 0:
            deltas["synthesized"] = delta_str(blocks_synthesized, comp_synthesized)

        comp_errors = get_events(comparison, "synthesis_error")
        comp_complete = get_events(comparison, "synthesis_complete")
        comp_total = len(comp_complete) + len(comp_errors)
        if comp_total > 0:
            comp_error_rate = len(comp_errors) / comp_total * 100
            deltas["error_rate"] = delta_str(error_rate, comp_error_rate, invert=True)

    return [
        {
            "label": "Audio Generated",
            "value": f"{audio_min:.1f} min",
            "delta": deltas.get("audio"),
            "help": "Total audio duration synthesized",
        },
        {
            "label": "Blocks Synthesized",
            "value": format_number(blocks_synthesized),
            "delta": deltas.get("synthesized"),
            "help": "Audio blocks that needed synthesis (cache misses)",
        },
        {
            "label": "Cache Hit Rate",
            "value": format_percent(cache_rate),
            "help": "Blocks served from cache vs total requested",
        },
        {
            "label": "Synth Error Rate",
            "value": format_percent(error_rate),
            "delta": deltas.get("error_rate"),
            "help": "Synthesis error rate",
        },
        {
            "label": "Avg Synth Latency",
            "value": format_duration(avg_latency),
            "help": "Average synthesis worker processing time",
        },
        {
            "label": "Gemini Cost",
            "value": format_cost(gemini_cost),
            "help": "Estimated Gemini API cost (input + output tokens)",
        },
    ]


def _volume_sparkline(df: pd.DataFrame) -> go.Figure | None:
    """Create volume over time sparkline."""
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    # Bin by hour
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
    apply_plotly_theme(fig)
    fig.update_layout(
        title="",
        height=150,
        margin=dict(l=0, r=0, t=10, b=30),
        xaxis=dict(showgrid=False, title=dict(text="")),
        yaxis=dict(showgrid=True, title=dict(text=""), gridcolor=COLORS["border"]),
        showlegend=False,
    )
    return fig


def _cache_summary(df: pd.DataFrame):
    """Display cache hit rates summary."""
    section_header("Cache Performance", "Hit rates across all caches")

    # Audio cache
    audio_hits = len(get_events(df, "cache_hit"))
    audio_misses = len(get_events(df, "synthesis_queued"))
    audio_rate = calculate_rate(audio_hits, audio_misses)

    # Document cache
    doc_hits = get_events(df, "document_cache_hit")
    doc_hit_count = len(doc_hits)

    # Extraction cache
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
        st.caption("URL and upload deduplication")

    with col3:
        st.markdown("**Extraction Cache**")
        st.markdown(f"### {format_percent(extraction_rate)}")
        st.caption(f"{format_number(extraction_hits)} hits / {format_number(extraction_misses)} pages processed")


def _event_breakdown(df: pd.DataFrame):
    """Display event type breakdown chart."""
    counts = df["event_type"].value_counts().head(15)
    if counts.empty:
        return

    section_header("Event Breakdown", "Top event types by count")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=counts.index,
            x=counts.values,
            orientation="h",
            marker=dict(
                color=COLORS["accent_blue"],
                line=dict(width=0),
            ),
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(200, len(counts) * 28),
        margin=dict(l=0, r=10, t=0, b=0),
        xaxis=dict(title=None, showgrid=True, gridcolor=COLORS["border"]),
        yaxis=dict(title=None, autorange="reversed"),
        showlegend=False,
    )
    apply_plotly_theme(fig)
    st.plotly_chart(fig, use_container_width=True)


def _queue_health(df: pd.DataFrame):
    """Display queue health summary."""
    section_header("Queue Health", "Current queue status")

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
                st.caption("No queue depth data")
        else:
            st.caption("No TTS queue data")

    with col2:
        if not detection_queued.empty:
            depths = detection_queued["queue_depth"].dropna()
            st.markdown("**Detection Queue**")
            if not depths.empty:
                st.markdown(f"Avg depth: **{depths.mean():.1f}** | Max: **{depths.max():.0f}**")
            else:
                st.caption("No queue depth data")
        else:
            st.caption("No detection queue data")


def render(df: pd.DataFrame, comparison_df: pd.DataFrame | None = None):
    """Render the overview tab."""
    if df.empty:
        empty_state("No data available for the selected time range")
        return

    # KPI row
    section_header("Key Metrics", "Executive summary")
    kpis = _get_kpi_data(df, comparison_df)
    kpi_row(kpis, cols=6)

    st.divider()

    # Volume sparkline
    st.markdown("**Request Volume Over Time**")
    fig = _volume_sparkline(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No request data")

    st.divider()

    # Two columns: cache summary + queue health
    col1, col2 = st.columns(2)
    with col1:
        _cache_summary(df)
    with col2:
        _queue_health(df)

    st.divider()

    # Event breakdown
    _event_breakdown(df)
