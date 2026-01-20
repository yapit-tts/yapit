"""Extraction tab - Gemini/LLM page extraction metrics."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_cost,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, calculate_rate, get_events
from dashboard.theme import COLORS, apply_plotly_theme

# Gemini 3 Flash Preview pricing
GEMINI_INPUT_COST_PER_M = 0.50  # $/M tokens
GEMINI_OUTPUT_COST_PER_M = 3.00  # $/M tokens (thoughts count as output)


def _calculate_costs(df: pd.DataFrame) -> dict:
    """Calculate token costs from extraction events."""
    complete = get_events(df, "page_extraction_complete")
    num_pages = len(complete)

    if complete.empty:
        return {
            "num_pages": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "input_cost": 0,
            "output_cost": 0,
            "total_cost": 0,
            # Per-page averages
            "prompt_per_page": 0,
            "candidates_per_page": 0,
            "thoughts_per_page": 0,
            "total_per_page": 0,
            "cost_per_page": 0,
        }

    prompt = complete["prompt_token_count"].fillna(0).sum()
    candidates = complete["candidates_token_count"].fillna(0).sum()
    thoughts = complete["thoughts_token_count"].fillna(0).sum()
    total = complete["total_token_count"].fillna(0).sum()

    input_cost = (prompt / 1_000_000) * GEMINI_INPUT_COST_PER_M
    output_cost = ((candidates + thoughts) / 1_000_000) * GEMINI_OUTPUT_COST_PER_M
    total_cost = input_cost + output_cost

    return {
        "num_pages": num_pages,
        "prompt_tokens": int(prompt),
        "candidates_tokens": int(candidates),
        "thoughts_tokens": int(thoughts),
        "total_tokens": int(total),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
        # Per-page averages
        "prompt_per_page": int(prompt / num_pages),
        "candidates_per_page": int(candidates / num_pages),
        "thoughts_per_page": int(thoughts / num_pages),
        "total_per_page": int(total / num_pages),
        "cost_per_page": total_cost / num_pages,
    }


def _summary_stats(df: pd.DataFrame):
    """Display summary statistics."""
    complete = get_events(df, "page_extraction_complete")
    errors = get_events(df, "page_extraction_error")
    cache_hits = get_events(df, "extraction_cache_hit")

    total_pages = len(complete)
    errored = len(errors)
    cached = len(cache_hits)
    success_rate = (total_pages / (total_pages + errored) * 100) if (total_pages + errored) > 0 else 0
    cache_rate = calculate_rate(cached, total_pages)

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Pages Processed", format_number(total_pages))
    with col2:
        st.metric("Cache Hits", format_number(cached))
    with col3:
        st.metric("Errors", format_number(errored))
    with col4:
        st.metric("Success Rate", format_percent(success_rate))
    with col5:
        st.metric("Cache Hit Rate", format_percent(cache_rate))


def _token_breakdown(df: pd.DataFrame):
    """Display token usage breakdown with per-page averages."""
    costs = _calculate_costs(df)
    complete = get_events(df, "page_extraction_complete")

    section_header("Token Usage", "Total and per-page breakdown")

    # Row 1: Total tokens
    st.markdown("**Totals**")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Input", format_number(costs["prompt_tokens"]))
    with col2:
        st.metric("Output", format_number(costs["candidates_tokens"]))
    with col3:
        st.metric("Thinking", format_number(costs["thoughts_tokens"]))
        if costs["total_tokens"] > 0:
            thinking_pct = costs["thoughts_tokens"] / costs["total_tokens"] * 100
            st.caption(f"{thinking_pct:.1f}% of total")
    with col4:
        st.metric("Total", format_number(costs["total_tokens"]))
    with col5:
        st.metric("Total Cost", format_cost(costs["total_cost"]))

    # Row 2: Per-page averages with std
    st.markdown("**Per Page (avg ± std)**")
    col1, col2, col3, col4, col5 = st.columns(5)

    # Calculate stds
    if not complete.empty:
        input_std = complete["prompt_token_count"].std()
        output_std = complete["candidates_token_count"].std()
        thinking_std = complete["thoughts_token_count"].std()
        total_std = complete["total_token_count"].std()
    else:
        input_std = output_std = thinking_std = total_std = 0

    with col1:
        st.metric("Input/pg", format_number(costs["prompt_per_page"]))
        st.caption(f"± {format_number(input_std)}")
    with col2:
        st.metric("Output/pg", format_number(costs["candidates_per_page"]))
        st.caption(f"± {format_number(output_std)}")
    with col3:
        st.metric("Thinking/pg", format_number(costs["thoughts_per_page"]))
        st.caption(f"± {format_number(thinking_std)}")
    with col4:
        st.metric("Total/pg", format_number(costs["total_per_page"]))
        st.caption(f"± {format_number(total_std)}")
    with col5:
        st.metric("Cost/pg", format_cost(costs["cost_per_page"]))


def _token_usage_chart(df: pd.DataFrame) -> go.Figure | None:
    """Token usage over time (stacked area) - total tokens."""
    complete = get_events(df, "page_extraction_complete")
    if complete.empty:
        return None

    complete = bin_by_time(complete, "1h")
    hourly = (
        complete.groupby("time_bin")
        .agg(
            prompt=("prompt_token_count", "sum"),
            candidates=("candidates_token_count", "sum"),
            thoughts=("thoughts_token_count", "sum"),
        )
        .reset_index()
    )

    if hourly.empty:
        return None

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["prompt"],
            mode="lines",
            name="Input",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(88, 166, 255, 0.6)",
            stackgroup="one",
            hovertemplate="Input: %{y:,.0f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["candidates"],
            mode="lines",
            name="Output",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(57, 217, 138, 0.6)",
            stackgroup="one",
            hovertemplate="Output: %{y:,.0f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["thoughts"],
            mode="lines",
            name="Thinking",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(163, 113, 247, 0.6)",
            stackgroup="one",
            hovertemplate="Thinking: %{y:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Total Token Usage Over Time (hourly)",
        height=350,
        xaxis_title="Time",
        yaxis_title="Tokens",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _tokens_per_page_chart(df: pd.DataFrame) -> go.Figure | None:
    """Average tokens per page over time."""
    complete = get_events(df, "page_extraction_complete")
    if complete.empty:
        return None

    complete = bin_by_time(complete, "1h")
    hourly = (
        complete.groupby("time_bin")
        .agg(
            pages=("event_type", "count"),
            prompt=("prompt_token_count", "sum"),
            candidates=("candidates_token_count", "sum"),
            thoughts=("thoughts_token_count", "sum"),
            total=("total_token_count", "sum"),
        )
        .reset_index()
    )

    if hourly.empty:
        return None

    # Calculate per-page averages
    hourly["total_per_page"] = hourly["total"] / hourly["pages"]
    hourly["input_per_page"] = hourly["prompt"] / hourly["pages"]
    hourly["output_per_page"] = hourly["candidates"] / hourly["pages"]
    hourly["thinking_per_page"] = hourly["thoughts"] / hourly["pages"]

    # Calculate cost per page
    hourly["cost_per_page"] = (
        (hourly["prompt"] / 1_000_000 * GEMINI_INPUT_COST_PER_M)
        + ((hourly["candidates"] + hourly["thoughts"]) / 1_000_000 * GEMINI_OUTPUT_COST_PER_M)
    ) / hourly["pages"]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["input_per_page"],
            mode="lines",
            name="Input",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(88, 166, 255, 0.6)",
            stackgroup="one",
            hovertemplate="Input: %{y:,.0f}/pg<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["output_per_page"],
            mode="lines",
            name="Output",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(57, 217, 138, 0.6)",
            stackgroup="one",
            hovertemplate="Output: %{y:,.0f}/pg<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["thinking_per_page"],
            mode="lines",
            name="Thinking",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(163, 113, 247, 0.6)",
            stackgroup="one",
            hovertemplate="Thinking: %{y:,.0f}/pg<extra></extra>",
        )
    )

    fig.update_layout(
        title="Tokens Per Page Over Time (hourly avg, stacked)",
        height=350,
        xaxis_title="Time",
        yaxis_title="Tokens per Page",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _cost_breakdown_pie(df: pd.DataFrame) -> go.Figure | None:
    """Cost breakdown pie chart."""
    costs = _calculate_costs(df)
    if costs["total_cost"] == 0:
        return None

    # Break down output cost into candidates vs thoughts
    complete = get_events(df, "page_extraction_complete")
    candidates = complete["candidates_token_count"].fillna(0).sum()
    thoughts = complete["thoughts_token_count"].fillna(0).sum()
    total_output = candidates + thoughts

    if total_output > 0:
        candidates_cost = (candidates / total_output) * costs["output_cost"]
        thoughts_cost = (thoughts / total_output) * costs["output_cost"]
    else:
        candidates_cost = 0
        thoughts_cost = 0

    labels = ["Input", "Output", "Thinking"]
    values = [costs["input_cost"], candidates_cost, thoughts_cost]
    colors = [COLORS["accent_blue"], COLORS["accent_teal"], COLORS["accent_purple"]]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors),
                hole=0.4,
                textinfo="label+percent",
                hovertemplate="%{label}: %{value:.4f}<extra></extra>",
            )
        ]
    )

    fig.update_layout(
        title="Cost Breakdown",
        height=300,
        showlegend=False,
    )
    apply_plotly_theme(fig)
    return fig


def _latency_histogram(df: pd.DataFrame) -> go.Figure | None:
    """Extraction latency distribution."""
    complete = get_events(df, "page_extraction_complete")
    if complete.empty or "duration_ms" not in complete.columns:
        # Try extracting from data blob if not in column
        return None

    # Check if we have latency data (might need to extract from another field)
    latencies = complete["duration_ms"].dropna() if "duration_ms" in complete.columns else pd.Series()

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

    fig.update_layout(
        title="Extraction Latency Distribution",
        height=300,
        xaxis_title="Latency (ms)",
        yaxis_title="Count",
    )
    apply_plotly_theme(fig)
    return fig


def _error_breakdown(df: pd.DataFrame) -> go.Figure | None:
    """Error type breakdown."""
    errors = get_events(df, "page_extraction_error")
    if errors.empty:
        return None

    # Extract status codes
    if "status_code" in errors.columns:
        status_counts = errors["status_code"].value_counts()
    else:
        # Try extracting from data blob
        errors_with_status = errors[
            errors["data"].apply(lambda d: "status_code" in d if isinstance(d, dict) else False)
        ]
        if errors_with_status.empty:
            return None
        status_counts = errors_with_status["data"].apply(lambda d: d.get("status_code", "Unknown")).value_counts()

    if status_counts.empty:
        return None

    # Map status codes to labels
    labels = []
    for code in status_counts.index:
        if code == 429:
            labels.append("429 (Rate Limit)")
        elif code == 500:
            labels.append("500 (Server Error)")
        elif code == 503:
            labels.append("503 (Unavailable)")
        elif code == 504:
            labels.append("504 (Timeout)")
        else:
            labels.append(str(code))

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=list(status_counts.values),
            y=labels,
            orientation="h",
            marker=dict(color=COLORS["error"]),
            hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Error Types",
        height=max(200, len(status_counts) * 40),
        xaxis_title="Count",
        yaxis_title=None,
    )
    apply_plotly_theme(fig)
    return fig


def _estimate_stats(df: pd.DataFrame):
    """Display extraction estimate statistics."""
    estimates = get_events(df, "extraction_estimate")
    if estimates.empty:
        st.caption("No extraction estimates logged yet")
        return

    # Extract data from blob
    estimates = estimates.copy()
    estimates["num_pages"] = estimates["data"].apply(lambda d: d.get("num_pages", 0) if isinstance(d, dict) else 0)
    estimates["text_pages"] = estimates["data"].apply(lambda d: d.get("text_pages", 0) if isinstance(d, dict) else 0)
    estimates["raster_pages"] = estimates["data"].apply(
        lambda d: d.get("raster_pages", 0) if isinstance(d, dict) else 0
    )
    estimates["total_text_chars"] = estimates["data"].apply(
        lambda d: d.get("total_text_chars", 0) if isinstance(d, dict) else 0
    )
    estimates["estimated_tokens"] = estimates["data"].apply(
        lambda d: d.get("estimated_tokens", 0) if isinstance(d, dict) else 0
    )
    estimates["tolerance"] = estimates["data"].apply(lambda d: d.get("tolerance", 0) if isinstance(d, dict) else 0)

    total_estimates = len(estimates)
    avg_pages = estimates["num_pages"].mean()
    avg_text_pages = estimates["text_pages"].mean()
    avg_raster_pages = estimates["raster_pages"].mean()
    avg_estimated = estimates["estimated_tokens"].mean()
    avg_tolerance = estimates["tolerance"].mean()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Documents", format_number(total_estimates))
    with col2:
        st.metric("Avg Pages", f"{avg_pages:.1f}")
    with col3:
        st.metric("Avg Text Pgs", f"{avg_text_pages:.1f}")
    with col4:
        st.metric("Avg Raster Pgs", f"{avg_raster_pages:.1f}")
    with col5:
        st.metric("Avg Est. Tokens", format_number(avg_estimated))
    with col6:
        st.metric("Avg Tolerance", f"{avg_tolerance:.0%}")


def _processor_stats(df: pd.DataFrame):
    """Stats by processor."""
    complete = get_events(df, "page_extraction_complete")
    errors = get_events(df, "page_extraction_error")

    if complete.empty and errors.empty:
        st.caption("No processor data")
        return

    all_events = pd.concat([complete, errors], ignore_index=True)
    if "processor_slug" not in all_events.columns or all_events["processor_slug"].isna().all():
        st.caption("No processor_slug data")
        return

    processors = (
        all_events.groupby("processor_slug")
        .agg(
            total=("event_type", "count"),
            completed=("event_type", lambda x: (x == "page_extraction_complete").sum()),
            errors=("event_type", lambda x: (x == "page_extraction_error").sum()),
            total_tokens=("total_token_count", "sum"),
        )
        .reset_index()
    )

    processors["success_rate"] = processors.apply(
        lambda r: r["completed"] / r["total"] * 100 if r["total"] > 0 else 0, axis=1
    )

    display_df = pd.DataFrame(
        {
            "Processor": processors["processor_slug"],
            "Pages": processors["total"],
            "Success": processors["completed"],
            "Errors": processors["errors"],
            "Success Rate": processors["success_rate"].apply(lambda x: f"{x:.1f}%"),
            "Total Tokens": processors["total_tokens"].apply(format_number),
        }
    )

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def render(df: pd.DataFrame):
    """Render the Extraction tab."""
    extraction_events = get_events(df, "page_extraction_complete")
    if extraction_events.empty and get_events(df, "page_extraction_error").empty:
        empty_state("No extraction data available", icon="📄")
        return

    # Summary stats
    section_header("Summary", "Page extraction statistics")
    _summary_stats(df)

    st.divider()

    # Token breakdown
    _token_breakdown(df)

    st.divider()

    # Estimate stats
    section_header("Extraction Estimates", "Pre-extraction document analysis")
    _estimate_stats(df)

    st.divider()

    # Processor stats
    section_header("By Processor", "Performance by extraction processor")
    _processor_stats(df)

    st.divider()

    # Charts
    section_header("Charts")

    # Row 1: Total tokens + per-page tokens
    col1, col2 = st.columns(2)
    with col1:
        fig = _token_usage_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No token usage data")

    with col2:
        fig = _tokens_per_page_chart(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No per-page data")

    # Row 2: Cost breakdown + errors
    col1, col2 = st.columns(2)
    with col1:
        fig = _cost_breakdown_pie(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No cost data")

    with col2:
        fig = _error_breakdown(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No errors (great!)")
