"""Overflow tab — RunPod serverless overflow (currently disabled).

Historical data only. The overflow scanner is disabled in production.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_number,
    format_percent,
    section_header,
)
from dashboard.data import bin_by_time, calculate_rate, get_events
from dashboard.theme import COLORS, apply_plotly_theme


def _summary_stats(df: pd.DataFrame):
    overflow = get_events(df, "job_overflow")
    overflow_complete = get_events(df, "overflow_complete")
    overflow_error = get_events(df, "overflow_error")

    total = len(overflow)
    completed = len(overflow_complete)
    errored = len(overflow_error)
    success_rate = calculate_rate(completed, errored) if (completed + errored) > 0 else 100

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Overflow Jobs", format_number(total))
    with col2:
        st.metric("Completed", format_number(completed))
    with col3:
        st.metric("Errors", format_number(errored))
    with col4:
        st.metric("Success Rate", format_percent(success_rate))


def _overflow_comparison(df: pd.DataFrame) -> go.Figure | None:
    synthesis = get_events(df, "synthesis_complete")
    overflow_count = len(get_events(df, "job_overflow"))
    local_count = len(synthesis)

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
    fig.update_layout(title="Local vs Overflow Processing", height=300, showlegend=False)
    apply_plotly_theme(fig)
    return fig


def _overflow_timeline(df: pd.DataFrame) -> go.Figure | None:
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


def _overflow_errors_timeline(df: pd.DataFrame) -> go.Figure | None:
    errors = get_events(df, "overflow_error")
    complete = get_events(df, "overflow_complete")

    if errors.empty and complete.empty:
        return None

    fig = go.Figure()
    for etype, color, label in [
        ("overflow_complete", COLORS["accent_teal"], "Completed"),
        ("overflow_error", COLORS["error"], "Errors"),
    ]:
        events = get_events(df, etype)
        if not events.empty:
            events = bin_by_time(events, "1h")
            hourly = events.groupby("time_bin").size().reset_index(name="count")
            fig.add_trace(
                go.Bar(
                    x=hourly["time_bin"],
                    y=hourly["count"],
                    name=label,
                    marker_color=color,
                    hovertemplate=f"{label}: %{{y}}<extra></extra>",
                )
            )

    fig.update_layout(
        title="Overflow Results Over Time (hourly)",
        height=300,
        barmode="stack",
        xaxis_title="Time",
        yaxis_title="Jobs",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def render(df: pd.DataFrame):
    """Render the Overflow tab."""
    st.caption("The overflow scanner is currently disabled in production. This tab shows historical data.")

    overflow = get_events(df, "job_overflow")
    overflow_complete = get_events(df, "overflow_complete")
    overflow_error = get_events(df, "overflow_error")

    if overflow.empty and overflow_complete.empty and overflow_error.empty:
        empty_state("No overflow data in this period", icon="📦")
        return

    section_header("Summary", "RunPod serverless overflow")
    _summary_stats(df)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        fig = _overflow_comparison(df)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No comparison data")
    with col2:
        fig = _overflow_timeline(df)
        if fig:
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No overflow timeline")

    fig = _overflow_errors_timeline(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
