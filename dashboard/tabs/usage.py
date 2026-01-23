"""Usage tab - Usage patterns, user stats, volume metrics."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    empty_state,
    format_number,
    section_header,
)
from dashboard.data import bin_by_time, get_events, get_events_multi
from dashboard.theme import COLORS, apply_plotly_theme, get_model_color


def _summary_stats(df: pd.DataFrame):
    """Display usage summary."""
    synthesis_queued = get_events(df, "synthesis_queued")
    synthesis_complete = get_events(df, "synthesis_complete")
    cache_hits = get_events(df, "cache_hit")

    total_requests = len(synthesis_queued) + len(cache_hits)
    total_audio_ms = synthesis_complete["audio_duration_ms"].sum()
    total_audio_min = total_audio_ms / 60000
    total_chars = synthesis_queued["text_length"].sum()
    unique_users = df["user_id"].nunique()
    unique_docs = df["document_id"].nunique()

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Requests", format_number(total_requests))
    with col2:
        st.metric("Audio Generated", f"{total_audio_min:.1f} min")
    with col3:
        st.metric("Characters", format_number(total_chars))
    with col4:
        st.metric("Unique Users", format_number(unique_users))
    with col5:
        st.metric("Documents", format_number(unique_docs))


def _usage_heatmap(df: pd.DataFrame) -> go.Figure | None:
    """Usage heatmap: hour of day × day of week."""
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    events = events.copy()
    events["hour"] = events["local_time"].dt.hour
    events["dayofweek"] = events["local_time"].dt.dayofweek  # 0=Monday

    # Aggregate
    heatmap_data = events.groupby(["dayofweek", "hour"]).size().reset_index(name="count")

    # Create pivot table
    pivot = heatmap_data.pivot(index="dayofweek", columns="hour", values="count").fillna(0)

    # Ensure all hours and days exist
    for h in range(24):
        if h not in pivot.columns:
            pivot[h] = 0
    for d in range(7):
        if d not in pivot.index:
            pivot.loc[d] = 0

    pivot = pivot.sort_index(axis=1).sort_index()

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hour_labels = [f"{h:02d}" for h in range(24)]

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=hour_labels,
            y=[day_names[i] for i in pivot.index],
            colorscale=[
                [0, COLORS["bg_card"]],
                [0.5, COLORS["accent_blue"]],
                [1, COLORS["accent_teal"]],
            ],
            hovertemplate="Day: %{y}<br>Hour: %{x}<br>Requests: %{z}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Usage Patterns (Hour × Day)",
        height=300,
        xaxis_title="Hour of Day",
        yaxis_title=None,
    )
    apply_plotly_theme(fig)
    return fig


def _model_popularity(df: pd.DataFrame) -> go.Figure | None:
    """Model usage bar chart."""
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    model_counts = events["model_slug"].value_counts()
    if model_counts.empty:
        return None

    colors = [get_model_color(m) for m in model_counts.index]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=list(model_counts.index),
            y=list(model_counts.values),
            marker_color=colors,
            hovertemplate="%{x}: %{y:,}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Model Popularity",
        height=300,
        xaxis_title=None,
        yaxis_title="Requests",
    )
    apply_plotly_theme(fig)
    return fig


def _voice_popularity(df: pd.DataFrame) -> go.Figure | None:
    """Top voices bar chart."""
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    voice_counts = events["voice_slug"].value_counts().head(10)
    if voice_counts.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=list(voice_counts.index),
            x=list(voice_counts.values),
            orientation="h",
            marker_color=COLORS["accent_purple"],
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Top 10 Voices",
        height=max(200, len(voice_counts) * 30),
        xaxis_title="Requests",
        yaxis_title=None,
        yaxis=dict(autorange="reversed"),
    )
    apply_plotly_theme(fig)
    return fig


def _model_usage_over_time(df: pd.DataFrame) -> go.Figure | None:
    """Model usage stacked area over time."""
    events = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if events.empty:
        return None

    events = bin_by_time(events, "1h")
    hourly = events.groupby(["time_bin", "model_slug"]).size().reset_index(name="count")

    if hourly.empty:
        return None

    fig = go.Figure()

    for model in sorted(hourly["model_slug"].dropna().unique()):
        model_data = hourly[hourly["model_slug"] == model]

        fig.add_trace(
            go.Scatter(
                x=model_data["time_bin"],
                y=model_data["count"],
                mode="lines",
                name=model,
                line=dict(width=0, color=get_model_color(model)),
                fill="tonexty",
                stackgroup="one",
                hovertemplate=f"<b>{model}</b>: %{{y}}<extra></extra>",
            )
        )

    fig.update_layout(
        title="Model Usage Over Time (hourly)",
        height=350,
        xaxis_title="Time",
        yaxis_title="Requests",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    apply_plotly_theme(fig)
    return fig


def _per_user_stats(df: pd.DataFrame):
    """Per-user usage statistics."""
    synthesis_queued = get_events(df, "synthesis_queued")
    cache_hits = get_events(df, "cache_hit")
    synthesis_complete = get_events(df, "synthesis_complete")

    all_requests = pd.concat([synthesis_queued, cache_hits], ignore_index=True)
    if all_requests.empty or "user_id" not in all_requests.columns:
        st.caption("No user data available")
        return

    # Per-user request counts
    user_requests = all_requests.groupby("user_id").size()

    # Per-user audio duration (from synthesis_complete)
    if not synthesis_complete.empty and "user_id" in synthesis_complete.columns:
        user_audio = synthesis_complete.groupby("user_id")["audio_duration_ms"].sum() / 60000  # minutes
    else:
        user_audio = pd.Series(dtype=float)

    # Per-user characters (from synthesis_queued)
    if not synthesis_queued.empty and "user_id" in synthesis_queued.columns:
        user_chars = synthesis_queued.groupby("user_id")["text_length"].sum()
    else:
        user_chars = pd.Series(dtype=float)

    section_header("Per-User Statistics", "Usage distribution across users")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Requests per User**")
        if not user_requests.empty:
            st.markdown(f"Mean: **{user_requests.mean():.1f}**")
            st.markdown(f"Median: **{user_requests.median():.1f}**")
            st.markdown(f"Max: **{user_requests.max():.0f}**")
        else:
            st.caption("No data")

    with col2:
        st.markdown("**Audio per User (min)**")
        if not user_audio.empty:
            st.markdown(f"Mean: **{user_audio.mean():.1f}**")
            st.markdown(f"Median: **{user_audio.median():.1f}**")
            st.markdown(f"Max: **{user_audio.max():.1f}**")
        else:
            st.caption("No data")

    with col3:
        st.markdown("**Characters per User**")
        if not user_chars.empty:
            st.markdown(f"Mean: **{user_chars.mean():,.0f}**")
            st.markdown(f"Median: **{user_chars.median():,.0f}**")
            st.markdown(f"Max: **{user_chars.max():,.0f}**")
        else:
            st.caption("No data")


def _user_distribution_chart(df: pd.DataFrame) -> go.Figure | None:
    """User request distribution histogram."""
    all_requests = get_events_multi(df, ["synthesis_queued", "cache_hit"])
    if all_requests.empty or "user_id" not in all_requests.columns:
        return None

    user_counts = all_requests.groupby("user_id").size()
    if user_counts.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=user_counts,
            nbinsx=20,
            marker=dict(color=COLORS["accent_blue"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Requests: %{x}<br>Users: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title="User Request Distribution",
        height=300,
        xaxis_title="Requests per User",
        yaxis_title="Number of Users",
    )
    apply_plotly_theme(fig)
    return fig


def _unique_users_over_time(df: pd.DataFrame) -> go.Figure | None:
    """Unique users per day."""
    if df.empty or "user_id" not in df.columns:
        return None

    df_copy = df.copy()
    df_copy["date"] = df_copy["local_time"].dt.date

    daily_users = df_copy.groupby("date")["user_id"].nunique().reset_index(name="unique_users")
    if daily_users.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily_users["date"],
            y=daily_users["unique_users"],
            mode="lines+markers",
            line=dict(color=COLORS["accent_cyan"], width=2),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(86, 212, 221, 0.15)",
            hovertemplate="%{x}: %{y} users<extra></extra>",
        )
    )

    fig.update_layout(
        title="Unique Users per Day",
        height=300,
        xaxis_title="Date",
        yaxis_title="Unique Users",
    )
    apply_plotly_theme(fig)
    return fig


def render(df: pd.DataFrame):
    """Render the Usage tab."""
    if df.empty:
        empty_state("No usage data available", icon="📈")
        return

    # Summary stats
    section_header("Summary", "Overall usage statistics")
    _summary_stats(df)

    st.divider()

    # Per-user stats
    _per_user_stats(df)

    st.divider()

    # Charts
    section_header("Charts")

    # Model usage over time (shows volume breakdown by model)
    fig = _model_usage_over_time(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # Row 3: Heatmap + unique users
    col1, col2 = st.columns(2)
    with col1:
        fig = _usage_heatmap(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Not enough data for heatmap")

    with col2:
        fig = _unique_users_over_time(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No user data")

    # Row 4: Model + voice popularity
    col1, col2 = st.columns(2)
    with col1:
        fig = _model_popularity(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No model data")

    with col2:
        fig = _voice_popularity(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No voice data")

    # Row 5: User distribution
    fig = _user_distribution_chart(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
