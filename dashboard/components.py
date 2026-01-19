"""Reusable dashboard components."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.theme import COLORS, apply_plotly_theme


def metric_card(
    label: str,
    value: str,
    delta: str | None = None,
    delta_color: str | None = None,
    help_text: str | None = None,
):
    """Display a metric with optional delta."""
    st.metric(
        label=label,
        value=value,
        delta=delta,
        delta_color=delta_color or "normal",
        help=help_text,
    )


def sparkline(
    df: pd.DataFrame,
    time_col: str = "local_time",
    value_col: str = "value",
    color: str | None = None,
    height: int = 60,
) -> go.Figure | None:
    """Create a minimal sparkline chart."""
    if df.empty:
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df[time_col],
            y=df[value_col],
            mode="lines",
            line=dict(color=color or COLORS["accent_teal"], width=2),
            fill="tozeroy",
            fillcolor="rgba(57, 217, 138, 0.1)",
            hovertemplate="%{y:.1f}<extra></extra>",
        )
    )

    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
        hovermode="x unified",
    )
    apply_plotly_theme(fig)
    return fig


def metric_with_sparkline(
    label: str,
    value: str,
    sparkline_data: pd.DataFrame | None = None,
    time_col: str = "local_time",
    value_col: str = "value",
    delta: str | None = None,
    color: str | None = None,
):
    """Display a metric card with an embedded sparkline."""
    st.markdown(f"**{label}**")
    st.markdown(f"### {value}")
    if delta:
        delta_color = COLORS["success"] if delta.startswith("+") or delta.startswith("↑") else COLORS["error"]
        st.markdown(f"<span style='color: {delta_color}'>{delta}</span>", unsafe_allow_html=True)

    if sparkline_data is not None and not sparkline_data.empty:
        fig = sparkline(sparkline_data, time_col, value_col, color)
        if fig:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def section_header(title: str, subtitle: str | None = None):
    """Display a section header with optional subtitle."""
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)


def empty_state(message: str, icon: str = "📊"):
    """Display an empty state message."""
    st.markdown(
        f"""
        <div style="text-align: center; padding: 40px; color: {COLORS["text_muted"]};">
            <div style="font-size: 48px; margin-bottom: 16px;">{icon}</div>
            <div>{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_row(metrics: list[dict], cols: int = 5):
    """Display a row of KPI metrics.

    Args:
        metrics: List of dicts with keys: label, value, delta (optional), help (optional)
        cols: Number of columns
    """
    columns = st.columns(cols)
    for i, metric in enumerate(metrics):
        with columns[i % cols]:
            metric_card(
                label=metric["label"],
                value=metric["value"],
                delta=metric.get("delta"),
                help_text=metric.get("help"),
            )


def format_duration(ms: float | None) -> str:
    """Format milliseconds as human-readable duration."""
    if ms is None or pd.isna(ms):
        return "-"
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f}s"
    else:
        return f"{ms / 60000:.1f}m"


def format_number(n: float | int | None, decimals: int = 0) -> str:
    """Format number with thousands separator."""
    if n is None or pd.isna(n):
        return "-"
    if decimals == 0:
        return f"{int(n):,}"
    return f"{n:,.{decimals}f}"


def format_percent(value: float | None, decimals: int = 1) -> str:
    """Format percentage."""
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.{decimals}f}%"


def format_bytes(b: float | None) -> str:
    """Format bytes as human-readable size."""
    if b is None or pd.isna(b):
        return "-"
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def format_cost(dollars: float | None) -> str:
    """Format cost in dollars."""
    if dollars is None or pd.isna(dollars):
        return "-"
    if dollars < 0.01:
        return f"${dollars:.4f}"
    elif dollars < 1:
        return f"${dollars:.3f}"
    else:
        return f"${dollars:.2f}"


def delta_str(current: float, previous: float, format_fn=None, invert: bool = False) -> str | None:
    """Calculate delta string between current and previous values.

    Args:
        current: Current value
        previous: Previous value
        format_fn: Function to format the delta value
        invert: If True, negative delta is good (e.g., for error rate)
    """
    if previous == 0:
        return None
    diff = current - previous
    pct = (diff / previous) * 100

    if format_fn:
        formatted = format_fn(abs(diff))
    else:
        formatted = f"{abs(pct):.1f}%"

    if diff > 0:
        return f"↑ {formatted}" if not invert else f"↑ {formatted}"
    elif diff < 0:
        return f"↓ {formatted}"
    return None


def worker_stats_table(df: pd.DataFrame, latency_col: str = "worker_latency_ms"):
    """Display per-worker statistics table."""
    if df.empty or "worker_id" not in df.columns:
        empty_state("No worker data available")
        return

    workers = (
        df.groupby("worker_id")
        .agg(
            count=(latency_col, "count"),
            p50=(latency_col, lambda x: x.quantile(0.5)),
            p95=(latency_col, lambda x: x.quantile(0.95)),
            errors=("event_type", lambda x: (x == "synthesis_error").sum() if "synthesis_error" in x.values else 0),
        )
        .reset_index()
    )

    workers.columns = ["Worker", "Jobs", "P50", "P95", "Errors"]
    workers["P50"] = workers["P50"].apply(format_duration)
    workers["P95"] = workers["P95"].apply(format_duration)

    st.dataframe(workers, hide_index=True, use_container_width=True)
