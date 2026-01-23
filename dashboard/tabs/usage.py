"""Usage tab - Usage patterns, user stats, volume metrics."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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


# === Rate Limit Insights ===


def _request_rate_distribution(df: pd.DataFrame) -> go.Figure | None:
    """Distribution of requests per minute per user."""
    synthesis_queued = get_events(df, "synthesis_queued")
    if synthesis_queued.empty or "user_id" not in synthesis_queued.columns:
        return None

    # Bin by minute and user
    synthesis_queued = synthesis_queued.copy()
    synthesis_queued["minute"] = synthesis_queued["local_time"].dt.floor("min")

    # Count requests per user per minute
    user_minute_counts = synthesis_queued.groupby(["user_id", "minute"]).size().reset_index(name="req_per_min")

    if user_minute_counts.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=user_minute_counts["req_per_min"],
            nbinsx=50,
            marker=dict(color=COLORS["accent_blue"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Req/min: %{x}<br>User-minutes: %{y}<extra></extra>",
        )
    )

    # Add reference lines for rate limits
    fig.add_vline(
        x=100,
        line_dash="dash",
        line_color=COLORS["warning"],
        annotation_text="100/min",
        annotation_position="top right",
    )
    fig.add_vline(
        x=300,
        line_dash="dash",
        line_color=COLORS["error"],
        annotation_text="300/min (limit)",
        annotation_position="top right",
    )

    fig.update_layout(
        title="Request Rate Distribution",
        height=350,
        xaxis_title="Requests per Minute (per user)",
        yaxis_title="Count",
    )
    apply_plotly_theme(fig)
    return fig


def _top_users_by_rate(df: pd.DataFrame):
    """Table of top users by peak request rate."""
    synthesis_queued = get_events(df, "synthesis_queued")
    if synthesis_queued.empty or "user_id" not in synthesis_queued.columns:
        st.caption("No request data for rate analysis")
        return

    # Bin by minute and user
    synthesis_queued = synthesis_queued.copy()
    synthesis_queued["minute"] = synthesis_queued["local_time"].dt.floor("min")

    # Count requests per user per minute
    user_minute_counts = synthesis_queued.groupby(["user_id", "minute"]).size().reset_index(name="req_per_min")

    # Aggregate per user: peak, avg, total
    user_stats = (
        user_minute_counts.groupby("user_id")
        .agg(
            peak_req_min=("req_per_min", "max"),
            avg_req_min=("req_per_min", "mean"),
            active_minutes=("minute", "count"),
        )
        .reset_index()
    )

    # Get total requests per user
    total_requests = synthesis_queued.groupby("user_id").size().reset_index(name="total_requests")
    user_stats = user_stats.merge(total_requests, on="user_id")

    # Sort by peak and take top 10
    user_stats = user_stats.sort_values("peak_req_min", ascending=False).head(10)

    if user_stats.empty:
        st.caption("No data")
        return

    display_df = pd.DataFrame(
        {
            "User ID": user_stats["user_id"].apply(lambda x: x[:8] + "..." if len(str(x)) > 8 else x),
            "Peak Req/Min": user_stats["peak_req_min"].astype(int),
            "Avg Req/Min": user_stats["avg_req_min"].round(1),
            "Active Mins": user_stats["active_minutes"].astype(int),
            "Total Requests": user_stats["total_requests"].apply(format_number),
        }
    )

    st.dataframe(display_df, hide_index=True, use_container_width=True)


def _chars_per_user_by_model(df: pd.DataFrame) -> go.Figure | None:
    """Character usage distribution per user, split by model type."""
    synthesis_queued = get_events(df, "synthesis_queued")
    if synthesis_queued.empty or "user_id" not in synthesis_queued.columns:
        return None

    # Classify as kokoro vs premium
    synthesis_queued = synthesis_queued.copy()
    synthesis_queued["model_type"] = synthesis_queued["model_slug"].apply(
        lambda m: "kokoro" if m and "kokoro" in m.lower() else "premium"
    )

    # Sum chars per user per model type
    user_chars = (
        synthesis_queued.groupby(["user_id", "model_type"])["text_length"].sum().reset_index(name="total_chars")
    )

    if user_chars.empty:
        return None

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Kokoro Chars/User", "Premium Chars/User"])

    # Kokoro histogram
    kokoro_data = user_chars[user_chars["model_type"] == "kokoro"]["total_chars"]
    if not kokoro_data.empty:
        fig.add_trace(
            go.Histogram(
                x=kokoro_data,
                nbinsx=30,
                marker=dict(color=COLORS["accent_teal"], line=dict(width=1, color=COLORS["border"])),
                hovertemplate="Chars: %{x:,.0f}<br>Users: %{y}<extra></extra>",
                name="Kokoro",
            ),
            row=1,
            col=1,
        )

    # Premium histogram
    premium_data = user_chars[user_chars["model_type"] == "premium"]["total_chars"]
    if not premium_data.empty:
        fig.add_trace(
            go.Histogram(
                x=premium_data,
                nbinsx=30,
                marker=dict(color=COLORS["accent_purple"], line=dict(width=1, color=COLORS["border"])),
                hovertemplate="Chars: %{x:,.0f}<br>Users: %{y}<extra></extra>",
                name="Premium",
            ),
            row=1,
            col=2,
        )

    fig.update_layout(
        title="Character Usage Distribution by Model Type",
        height=350,
        showlegend=False,
    )
    fig.update_xaxes(title_text="Characters", row=1, col=1)
    fig.update_xaxes(title_text="Characters", row=1, col=2)
    fig.update_yaxes(title_text="Users", row=1, col=1)
    fig.update_yaxes(title_text="Users", row=1, col=2)
    apply_plotly_theme(fig)
    return fig


def _pages_per_user_distribution(df: pd.DataFrame) -> go.Figure | None:
    """Distribution of pages extracted per user."""
    extraction = get_events(df, "page_extraction_complete")
    if extraction.empty:
        return None

    # Check if user_id exists and has non-null values
    if "user_id" not in extraction.columns or extraction["user_id"].isna().all():
        return None

    # Count pages per user (excluding null user_ids)
    valid_extraction = extraction.dropna(subset=["user_id"])
    if valid_extraction.empty:
        return None

    user_pages = valid_extraction.groupby("user_id").size()
    if user_pages.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=user_pages,
            nbinsx=30,
            marker=dict(color=COLORS["accent_coral"], line=dict(width=1, color=COLORS["border"])),
            hovertemplate="Pages: %{x}<br>Users: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Pages Extracted per User",
        height=300,
        xaxis_title="Pages",
        yaxis_title="Number of Users",
    )
    apply_plotly_theme(fig)
    return fig


def _monthly_usage_trends(df: pd.DataFrame) -> go.Figure | None:
    """Monthly usage trends: average chars/tokens per user."""
    synthesis_queued = get_events(df, "synthesis_queued")
    extraction = get_events(df, "page_extraction_complete")

    if synthesis_queued.empty and extraction.empty:
        return None

    # Need user_id to calculate per-user averages
    has_voice_users = not synthesis_queued.empty and "user_id" in synthesis_queued.columns
    has_extraction_users = not extraction.empty and "user_id" in extraction.columns

    if not has_voice_users and not has_extraction_users:
        return None

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Avg Voice Chars/User by Month", "Avg Extraction Tokens/User by Month"],
    )

    # Voice characters by model type (average per user)
    if has_voice_users:
        synthesis_queued = synthesis_queued.copy()
        synthesis_queued["month"] = synthesis_queued["local_time"].dt.to_period("M").astype(str)
        synthesis_queued["model_type"] = synthesis_queued["model_slug"].apply(
            lambda m: "Kokoro" if m and "kokoro" in m.lower() else "Premium"
        )

        # Calculate per-user average: total chars / unique users per month per model_type
        monthly_stats = (
            synthesis_queued.groupby(["month", "model_type"])
            .agg(total_chars=("text_length", "sum"), unique_users=("user_id", "nunique"))
            .reset_index()
        )
        monthly_stats["avg_chars_per_user"] = monthly_stats["total_chars"] / monthly_stats["unique_users"]

        for model_type, color in [("Kokoro", COLORS["accent_teal"]), ("Premium", COLORS["accent_purple"])]:
            data = monthly_stats[monthly_stats["model_type"] == model_type]
            if not data.empty:
                fig.add_trace(
                    go.Bar(
                        x=data["month"],
                        y=data["avg_chars_per_user"],
                        name=model_type,
                        marker_color=color,
                        hovertemplate=f"{model_type}: %{{y:,.0f}} chars/user<extra></extra>",
                    ),
                    row=1,
                    col=1,
                )

    # Extraction tokens (average per user)
    if has_extraction_users:
        extraction = extraction.dropna(subset=["user_id"]).copy()
        if not extraction.empty:
            extraction["month"] = extraction["local_time"].dt.to_period("M").astype(str)

            monthly_stats = (
                extraction.groupby("month")
                .agg(total_tokens=("total_token_count", "sum"), unique_users=("user_id", "nunique"))
                .reset_index()
            )
            monthly_stats["avg_tokens_per_user"] = monthly_stats["total_tokens"] / monthly_stats["unique_users"]

            if not monthly_stats.empty:
                fig.add_trace(
                    go.Bar(
                        x=monthly_stats["month"],
                        y=monthly_stats["avg_tokens_per_user"],
                        name="Tokens",
                        marker_color=COLORS["accent_coral"],
                        hovertemplate="Avg: %{y:,.0f} tokens/user<extra></extra>",
                        showlegend=False,
                    ),
                    row=1,
                    col=2,
                )

    fig.update_layout(
        title="Monthly Usage Trends (Average per User)",
        height=350,
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(title_text="Month", row=1, col=1)
    fig.update_xaxes(title_text="Month", row=1, col=2)
    fig.update_yaxes(title_text="Chars/User", row=1, col=1)
    fig.update_yaxes(title_text="Tokens/User", row=1, col=2)
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

    # Rate limit insights
    section_header("Rate Limit Insights", "Request rate patterns and limits")

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = _request_rate_distribution(df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No request rate data")

    with col2:
        st.markdown("**Top Users by Peak Rate**")
        _top_users_by_rate(df)

    st.divider()

    # Monthly usage trends
    section_header("Monthly Usage Trends", "Average usage per user by month")

    fig = _monthly_usage_trends(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No monthly data")

    st.divider()

    # Usage distributions
    section_header("Usage Distributions", "Character and page usage by user (for selected period)")

    fig = _chars_per_user_by_model(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No character usage data")

    fig = _pages_per_user_distribution(df)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No page extraction data")

    st.divider()

    # Charts
    section_header("Activity Charts")

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
