"""Documents tab — merged extraction, detection, website fetching, and batch jobs."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_cost,
    format_duration,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import (
    GEMINI_INPUT_COST_PER_M,
    GEMINI_OUTPUT_COST_PER_M,
    bin_by_time,
    calculate_gemini_cost,
    calculate_rate,
    get_events,
)
from dashboard.theme import COLORS, apply_plotly_theme

# ── Summary KPIs ──────────────────────────────────────────────────────────────


def _summary_kpis(df: pd.DataFrame):
    """Top-level document pipeline KPIs."""
    ext_complete = get_events(df, "page_extraction_complete")
    ext_errors = get_events(df, "page_extraction_error")
    det_complete = get_events(df, "detection_complete")
    det_errors = get_events(df, "detection_error")
    website = get_events(df, "website_extraction")
    batch_submitted = get_events(df, "batch_job_submitted")

    gemini_cost = calculate_gemini_cost(ext_complete)

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Pages Extracted", format_number(len(ext_complete)))
    with col2:
        st.metric("Extraction Errors", format_number(len(ext_errors)))
    with col3:
        st.metric("Detection Jobs", format_number(len(det_complete) + len(det_errors)))
    with col4:
        st.metric("Website Extractions", format_number(len(website)))
    with col5:
        st.metric("Batch Jobs", format_number(len(batch_submitted)))
    with col6:
        st.metric("Gemini Cost", format_cost(gemini_cost))


# ── Extraction (Gemini) ──────────────────────────────────────────────────────


def _calculate_costs(df: pd.DataFrame) -> dict:
    """Calculate token costs from extraction events."""
    complete = get_events(df, "page_extraction_complete")
    num_pages = len(complete)

    if complete.empty:
        return {
            k: 0
            for k in [
                "num_pages",
                "prompt_tokens",
                "candidates_tokens",
                "thoughts_tokens",
                "total_tokens",
                "input_cost",
                "output_cost",
                "total_cost",
                "prompt_per_page",
                "candidates_per_page",
                "thoughts_per_page",
                "total_per_page",
                "cost_per_page",
            ]
        }

    prompt = complete["prompt_token_count"].fillna(0).sum()
    candidates = complete["candidates_token_count"].fillna(0).sum()
    thoughts = complete["thoughts_token_count"].fillna(0).sum()
    total = complete["total_token_count"].fillna(0).sum()

    input_cost = (prompt / 1e6) * GEMINI_INPUT_COST_PER_M
    output_cost = ((candidates + thoughts) / 1e6) * GEMINI_OUTPUT_COST_PER_M
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
        "prompt_per_page": int(prompt / num_pages),
        "candidates_per_page": int(candidates / num_pages),
        "thoughts_per_page": int(thoughts / num_pages),
        "total_per_page": int(total / num_pages),
        "cost_per_page": total_cost / num_pages,
    }


def _extraction_summary(df: pd.DataFrame):
    """Extraction summary stats."""
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
    """Token usage breakdown with per-page averages."""
    costs = _calculate_costs(df)
    complete = get_events(df, "page_extraction_complete")

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

    st.markdown("**Per Page (avg +/- std)**")
    col1, col2, col3, col4, col5 = st.columns(5)
    if not complete.empty:
        input_std = complete["prompt_token_count"].std()
        output_std = complete["candidates_token_count"].std()
        thinking_std = complete["thoughts_token_count"].std()
        total_std = complete["total_token_count"].std()
    else:
        input_std = output_std = thinking_std = total_std = 0

    with col1:
        st.metric("Input/pg", format_number(costs["prompt_per_page"]))
        st.caption(f"+/- {format_number(input_std)}")
    with col2:
        st.metric("Output/pg", format_number(costs["candidates_per_page"]))
        st.caption(f"+/- {format_number(output_std)}")
    with col3:
        st.metric("Thinking/pg", format_number(costs["thoughts_per_page"]))
        st.caption(f"+/- {format_number(thinking_std)}")
    with col4:
        st.metric("Total/pg", format_number(costs["total_per_page"]))
        st.caption(f"+/- {format_number(total_std)}")
    with col5:
        st.metric("Cost/pg", format_cost(costs["cost_per_page"]))


def _prompt_cache_section(df: pd.DataFrame):
    """Gemini prompt cache utilization."""
    complete = get_events(df, "page_extraction_complete")
    if complete.empty or "cached_content_token_count" not in complete.columns:
        st.caption("No cache data")
        return

    total_prompt = complete["prompt_token_count"].fillna(0).sum()
    total_cached = complete["cached_content_token_count"].fillna(0).sum()
    cache_pct = (total_cached / total_prompt * 100) if total_prompt > 0 else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Overall Cache Rate", format_percent(cache_pct))
    with col2:
        st.metric("Cached Input Tokens", format_number(int(total_cached)))
    with col3:
        st.metric("Uncached Input Tokens", format_number(int(total_prompt - total_cached)))

    # Compute hourly cache data once for both charts
    hourly_cache = _compute_hourly_cache(complete)

    col1, col2 = st.columns(2)
    with col1:
        fig = _prompt_cache_utilization_chart(hourly_cache)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No cache trend data")
    with col2:
        fig = _cached_vs_uncached_chart(hourly_cache)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No cache trend data")


def _compute_hourly_cache(complete: pd.DataFrame) -> pd.DataFrame | None:
    """Compute hourly prompt/cached token aggregation. Shared by both cache charts."""
    if complete.empty or "cached_content_token_count" not in complete.columns:
        return None

    binned = bin_by_time(complete, "1h")
    hourly = (
        binned.groupby("time_bin")
        .agg(
            prompt=("prompt_token_count", "sum"),
            cached=("cached_content_token_count", "sum"),
        )
        .reset_index()
    )

    if hourly.empty or hourly["prompt"].sum() == 0:
        return None
    return hourly


def _prompt_cache_utilization_chart(hourly: pd.DataFrame | None) -> go.Figure | None:
    if hourly is None:
        return None

    hourly = hourly.copy()
    hourly["cache_pct"] = (hourly["cached"] / hourly["prompt"].replace(0, pd.NA) * 100).fillna(0)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["cache_pct"],
            mode="lines+markers",
            name="Cache %",
            line=dict(color=COLORS["accent_cyan"], width=2),
            marker=dict(size=4),
            fill="tozeroy",
            fillcolor="rgba(86, 212, 221, 0.15)",
            hovertemplate="%{y:.1f}% cached<extra></extra>",
        )
    )

    fig.update_layout(
        title="Prompt Cache Utilization (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="% Cached",
        yaxis=dict(range=[0, max(hourly["cache_pct"].max() * 1.1, 10)]),
    )
    apply_plotly_theme(fig)
    return fig


def _cached_vs_uncached_chart(hourly: pd.DataFrame | None) -> go.Figure | None:
    if hourly is None:
        return None

    hourly = hourly.copy()
    hourly["uncached"] = (hourly["prompt"] - hourly["cached"]).clip(lower=0)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["cached"],
            mode="lines",
            name="Cached",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(86, 212, 221, 0.6)",
            stackgroup="one",
            hovertemplate="Cached: %{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=hourly["time_bin"],
            y=hourly["uncached"],
            mode="lines",
            name="Uncached",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(88, 166, 255, 0.6)",
            stackgroup="one",
            hovertemplate="Uncached: %{y:,.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Cached vs Uncached Input Tokens (hourly)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Input Tokens",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _token_usage_chart(df: pd.DataFrame) -> go.Figure | None:
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
    for name, col, color in [
        ("Input", "prompt", "rgba(88, 166, 255, 0.6)"),
        ("Output", "candidates", "rgba(57, 217, 138, 0.6)"),
        ("Thinking", "thoughts", "rgba(163, 113, 247, 0.6)"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=hourly["time_bin"],
                y=hourly[col],
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
        title="Total Token Usage (hourly, stacked)",
        height=300,
        xaxis_title="Time",
        yaxis_title="Tokens",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _cost_breakdown_pie(df: pd.DataFrame) -> go.Figure | None:
    costs = _calculate_costs(df)
    if costs["total_cost"] == 0:
        return None

    complete = get_events(df, "page_extraction_complete")
    candidates = complete["candidates_token_count"].fillna(0).sum()
    thoughts = complete["thoughts_token_count"].fillna(0).sum()
    total_output = candidates + thoughts

    if total_output > 0:
        candidates_cost = (candidates / total_output) * costs["output_cost"]
        thoughts_cost = (thoughts / total_output) * costs["output_cost"]
    else:
        candidates_cost = thoughts_cost = 0

    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Input", "Output", "Thinking"],
                values=[costs["input_cost"], candidates_cost, thoughts_cost],
                marker=dict(colors=[COLORS["accent_blue"], COLORS["accent_teal"], COLORS["accent_purple"]]),
                hole=0.4,
                textinfo="label+percent",
                hovertemplate="%{label}: $%{value:.4f}<extra></extra>",
            )
        ]
    )
    fig.update_layout(title="Cost Breakdown", height=300, showlegend=False)
    apply_plotly_theme(fig)
    return fig


def _extraction_error_breakdown(df: pd.DataFrame) -> go.Figure | None:
    errors = get_events(df, "page_extraction_error")
    if errors.empty:
        return None

    if "status_code" in errors.columns:
        status_counts = errors["status_code"].dropna().value_counts()
    else:
        return None

    if status_counts.empty:
        return None

    label_map = {429: "429 (Rate Limit)", 500: "500 (Server Error)", 503: "503 (Unavailable)", 504: "504 (Timeout)"}
    labels = [label_map.get(int(c), str(c)) for c in status_counts.index]

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
        title="Extraction Error Types",
        height=max(200, len(status_counts) * 40),
        xaxis_title="Count",
        yaxis_title=None,
    )
    apply_plotly_theme(fig)
    return fig


def _estimate_section(df: pd.DataFrame):
    """Extraction estimate stats and accuracy."""
    estimates = get_events(df, "extraction_estimate")
    if estimates.empty:
        st.caption("No extraction estimates logged")
        return

    estimates = estimates.copy()
    for field in ["num_pages", "text_pages", "raster_pages", "estimated_tokens"]:
        estimates[field] = estimates["data"].apply(lambda d: d.get(field, 0) if isinstance(d, dict) else 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Documents", format_number(len(estimates)))
    with col2:
        st.metric("Avg Pages", f"{estimates['num_pages'].mean():.1f}")
    with col3:
        st.metric("Avg Text Pgs", f"{estimates['text_pages'].mean():.1f}")
    with col4:
        st.metric("Avg Est. Tokens", format_number(estimates["estimated_tokens"].mean()))


def _processor_stats(df: pd.DataFrame):
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
    st.dataframe(display_df, hide_index=True, width="stretch")


# ── Detection (YOLO) ─────────────────────────────────────────────────────────


def _detection_summary(df: pd.DataFrame):
    queued = get_events(df, "detection_queued")
    complete = get_events(df, "detection_complete")
    errors = get_events(df, "detection_error")
    mismatches = get_events(df, "figure_count_mismatch")

    completed = len(complete)
    errored = len(errors)
    error_rate = (errored / (completed + errored) * 100) if (completed + errored) > 0 else 0

    figures_total = 0
    if not complete.empty:
        figures_total = complete["data"].apply(lambda d: d.get("figures_count", 0) if isinstance(d, dict) else 0).sum()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Jobs Queued", format_number(len(queued)))
    with col2:
        st.metric("Completed", format_number(completed))
    with col3:
        st.metric("Errors", format_number(errored))
    with col4:
        st.metric("Error Rate", f"{error_rate:.1f}%")
    with col5:
        st.metric("Figures Detected", format_number(figures_total))
    with col6:
        st.metric("Mismatches", format_number(len(mismatches)))


def _detection_worker_table(df: pd.DataFrame):
    complete = get_events(df, "detection_complete")
    errors = get_events(df, "detection_error")
    if complete.empty and errors.empty:
        st.caption("No detection worker data")
        return

    all_events = pd.concat([complete, errors], ignore_index=True)
    if "worker_id" not in all_events.columns or all_events["worker_id"].isna().all():
        st.caption("No worker_id data")
        return

    workers = (
        all_events.groupby("worker_id")
        .agg(
            jobs=("event_type", "count"),
            completed=("event_type", lambda x: (x == "detection_complete").sum()),
            errors=("event_type", lambda x: (x == "detection_error").sum()),
            p50=("worker_latency_ms", lambda x: x.quantile(0.5)),
            p95=("worker_latency_ms", lambda x: x.quantile(0.95)),
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
            "P50": workers["p50"].apply(format_duration),
            "P95": workers["p95"].apply(format_duration),
            "Figures": workers["figures"],
        }
    )
    st.dataframe(display_df, hide_index=True, width="stretch")


def _detection_throughput_chart(df: pd.DataFrame) -> go.Figure | None:
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
            marker=dict(size=5),
            fill="tozeroy",
            fillcolor="rgba(163, 113, 247, 0.15)",
            hovertemplate="%{y} detections<extra></extra>",
        )
    )
    fig.update_layout(title="Detection Throughput (hourly)", height=280, xaxis_title="Time", yaxis_title="Jobs")
    apply_plotly_theme(fig)
    return fig


def _detection_latency_chart(df: pd.DataFrame) -> go.Figure | None:
    complete = get_events(df, "detection_complete")
    if complete.empty:
        return None
    latencies = complete["worker_latency_ms"].dropna()
    if latencies.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=complete.loc[latencies.index, "local_time"],
            y=latencies,
            mode="markers",
            marker=dict(size=5, color=COLORS["accent_purple"], opacity=0.7),
            hovertemplate="Latency: %{y:.0f}ms<br>%{x}<extra></extra>",
        )
    )
    fig.update_layout(title="Detection Latency Over Time", height=280, xaxis_title="Time", yaxis_title="Latency (ms)")
    apply_plotly_theme(fig)
    return fig


def _detection_latency_histogram(df: pd.DataFrame) -> go.Figure | None:
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
        title="Detection Latency Distribution", height=280, xaxis_title="Latency (ms)", yaxis_title="Count"
    )
    apply_plotly_theme(fig)
    return fig


def _figures_per_page_chart(df: pd.DataFrame) -> go.Figure | None:
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
    fig.update_layout(title="Figures Detected Per Page", height=280, xaxis_title="Figures", yaxis_title="Pages")
    apply_plotly_theme(fig)
    return fig


def _figure_mismatch_chart(df: pd.DataFrame) -> go.Figure | None:
    mismatches = get_events(df, "figure_count_mismatch")
    if mismatches.empty:
        return None

    mismatches = mismatches.copy()
    mismatches["yolo_count"] = mismatches["data"].apply(lambda d: d.get("yolo_count", 0) if isinstance(d, dict) else 0)
    mismatches["gemini_count"] = mismatches["data"].apply(
        lambda d: d.get("gemini_count", 0) if isinstance(d, dict) else 0
    )
    mismatches["delta"] = mismatches["data"].apply(lambda d: d.get("delta", 0) if isinstance(d, dict) else 0)

    colors = mismatches["delta"].apply(lambda d: COLORS["error"] if d > 0 else COLORS["accent_teal"])

    fig = go.Figure()
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

    max_val = max(mismatches["yolo_count"].max(), mismatches["gemini_count"].max(), 1) + 1
    fig.add_trace(
        go.Scatter(
            x=[0, max_val],
            y=[0, max_val],
            mode="lines",
            line=dict(color=COLORS["text_muted"], width=1, dash="dash"),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        title="Figure Count: YOLO vs Gemini",
        height=300,
        xaxis_title="YOLO Detected",
        yaxis_title="Gemini Placeholders",
    )
    apply_plotly_theme(fig)
    return fig


# ── Website & URL Fetching ────────────────────────────────────────────────────


def _website_fetching_section(df: pd.DataFrame):
    """Website extraction, URL fetch, and Playwright stats."""
    website = get_events(df, "website_extraction")
    url_fetch = get_events(df, "url_fetch")
    playwright = get_events(df, "playwright_fetch")
    markxiv = get_events(df, "markxiv_error")
    fallback = get_events(df, "html_fallback_triggered")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Website Extractions", format_number(len(website)))
        if not website.empty and "duration_ms" in website.columns:
            dur = website["duration_ms"].dropna()
            if not dur.empty:
                st.caption(f"P50: {format_duration(dur.median())}")
    with col2:
        st.metric("URL Fetches", format_number(len(url_fetch)))
        if not url_fetch.empty:
            url_errors = len(
                url_fetch[url_fetch["data"].apply(lambda d: "error" in d if isinstance(d, dict) else False)]
            )
            st.caption(f"{url_errors} errors")
    with col3:
        st.metric("Playwright (JS)", format_number(len(playwright)))
        if not playwright.empty:
            pw_errors = len(
                playwright[playwright["data"].apply(lambda d: "error" in d if isinstance(d, dict) else False)]
            )
            st.caption(f"{pw_errors} errors")
    with col4:
        st.metric("HTML Fallbacks", format_number(len(fallback)))
    with col5:
        st.metric("arXiv Errors", format_number(len(markxiv)))


# ── Batch Jobs ────────────────────────────────────────────────────────────────


def _batch_jobs_section(df: pd.DataFrame):
    """Gemini batch extraction job stats."""
    submitted = get_events(df, "batch_job_submitted")
    complete = get_events(df, "batch_job_complete")
    failed = get_events(df, "batch_job_failed")

    total = len(submitted)
    if total == 0:
        st.caption("No batch jobs in this period")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Submitted", format_number(total))
    with col2:
        st.metric("Completed", format_number(len(complete)))
    with col3:
        st.metric("Failed", format_number(len(failed)))

    # Timeline if enough data
    all_batch = pd.concat([submitted, complete, failed], ignore_index=True)
    if len(all_batch) > 1:
        all_batch = all_batch.sort_values("local_time")
        fig = go.Figure()
        for etype, color, label in [
            ("batch_job_submitted", COLORS["accent_blue"], "Submitted"),
            ("batch_job_complete", COLORS["accent_teal"], "Completed"),
            ("batch_job_failed", COLORS["error"], "Failed"),
        ]:
            events = all_batch[all_batch["event_type"] == etype]
            if not events.empty:
                fig.add_trace(
                    go.Scatter(
                        x=events["local_time"],
                        y=[label] * len(events),
                        mode="markers",
                        name=label,
                        marker=dict(size=12, color=color, symbol="diamond"),
                        hovertemplate=f"{label}<br>%{{x}}<extra></extra>",
                    )
                )
        fig.update_layout(title="Batch Job Timeline", height=200, showlegend=False)
        apply_plotly_theme(fig)
        st.plotly_chart(fig, width="stretch")


# ── Main Render ───────────────────────────────────────────────────────────────


def render(df: pd.DataFrame):
    """Render the Documents tab."""
    has_extraction = (
        not get_events(df, "page_extraction_complete").empty or not get_events(df, "page_extraction_error").empty
    )
    has_detection = not get_events(df, "detection_queued").empty or not get_events(df, "detection_complete").empty
    has_website = not get_events(df, "website_extraction").empty or not get_events(df, "url_fetch").empty

    if not has_extraction and not has_detection and not has_website:
        empty_state("No document processing data available", icon="📄")
        return

    # Top-level KPIs
    section_header("Summary", "Document processing pipeline")
    _summary_kpis(df)

    st.divider()

    # ── Extraction (Gemini) ──
    if has_extraction:
        section_header("Extraction (Gemini)", "AI page extraction")
        _extraction_summary(df)

        st.divider()
        section_header("Token Usage", "Total and per-page breakdown")
        _token_breakdown(df)

        st.divider()
        section_header("Gemini Prompt Cache", "Cached tokens are cheaper and faster")
        _prompt_cache_section(df)

        st.divider()
        section_header("Estimates", "Pre-extraction document analysis")
        _estimate_section(df)

        st.divider()
        section_header("By Processor")
        _processor_stats(df)

        st.divider()
        section_header("Extraction Charts")

        col1, col2 = st.columns(2)
        with col1:
            fig = _token_usage_chart(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No token data")
        with col2:
            fig = _cost_breakdown_pie(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No cost data")

        fig = _extraction_error_breakdown(df)
        if fig:
            st.plotly_chart(fig, width="stretch")

        st.divider()

    # ── Detection (YOLO) ──
    if has_detection:
        section_header("Detection (YOLO)", "Figure detection in PDFs")
        _detection_summary(df)

        section_header("Detection Workers")
        _detection_worker_table(df)

        col1, col2 = st.columns(2)
        with col1:
            fig = _detection_throughput_chart(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No throughput data")
        with col2:
            fig = _detection_latency_chart(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No latency data")

        col1, col2 = st.columns(2)
        with col1:
            fig = _detection_latency_histogram(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No latency data")
        with col2:
            fig = _figures_per_page_chart(df)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("No figures data")

        fig = _figure_mismatch_chart(df)
        if fig:
            st.plotly_chart(fig, width="stretch")

        st.divider()

    # ── Website & URL ──
    section_header("Website & URL Fetching", "Content download pipeline")
    _website_fetching_section(df)

    st.divider()

    # ── Batch Jobs ──
    section_header("Batch Jobs", "Gemini batch extraction (large documents)")
    _batch_jobs_section(df)
