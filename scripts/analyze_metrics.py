# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich", "matplotlib", "pandas"]
# ///
"""Metrics analysis with sensible defaults.

Run without args for comprehensive overview:
    uv run scripts/analyze_metrics.py

Filter by time:
    uv run scripts/analyze_metrics.py --since "1 hour"

Show plots (saved to metrics/plots/):
    uv run scripts/analyze_metrics.py --plot
"""

import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend - always save to file
import matplotlib.pyplot as plt
import pandas as pd
import tyro
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def parse_since(since: str) -> datetime:
    """Parse relative or absolute time string. Returns UTC for SQLite comparison."""
    since = since.strip().lower()
    now = datetime.now(UTC).replace(tzinfo=None)  # SQLite stores naive UTC timestamps

    if "hour" in since:
        hours = int(since.split()[0])
        return now - timedelta(hours=hours)
    if "day" in since:
        days = int(since.split()[0])
        return now - timedelta(days=days)
    if "week" in since:
        weeks = int(since.split()[0])
        return now - timedelta(weeks=weeks)
    if "minute" in since:
        minutes = int(since.split()[0])
        return now - timedelta(minutes=minutes)

    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(since, fmt)
        except ValueError:
            continue

    raise ValueError(f"Could not parse time: {since}")


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"Error: Metrics database not found at {db_path}")
        print("Run 'make dev-cpu' to start the backend and generate metrics.")
        sys.exit(1)
    return sqlite3.connect(db_path)


def load_events(conn: sqlite3.Connection, since: datetime) -> pd.DataFrame:
    query = """
        SELECT *,
               datetime(timestamp, 'localtime') as local_time
        FROM metrics_event
        WHERE timestamp >= ?
        ORDER BY timestamp
    """
    df = pd.read_sql_query(query, conn, params=[since.isoformat()])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["local_time"] = pd.to_datetime(df["local_time"])
    return df


def print_health_summary(df: pd.DataFrame, console: Console) -> None:
    if df.empty:
        console.print("[yellow]No events found in time range[/yellow]")
        return

    table = Table(title="Event Counts", box=box.ROUNDED)
    table.add_column("Event Type", style="cyan")
    table.add_column("Count", justify="right")

    counts = df["event_type"].value_counts()
    for event_type, count in counts.items():
        table.add_row(event_type, str(count))

    console.print(table)

    time_range = df["local_time"].max() - df["local_time"].min()
    console.print(f"\n[dim]Time range: {df['local_time'].min()} → {df['local_time'].max()} ({time_range})[/dim]")


def print_latency_stats(df: pd.DataFrame, console: Console) -> None:
    """Latency breakdown:
    - Queue wait: time from synthesis_queued to synthesis_started (waiting in Redis queue)
    - Worker time: time from synthesis_started to synthesis_complete (actual TTS processing)
    - Total: queue wait + worker time (full request latency)
    """
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    if synthesis.empty:
        console.print("[yellow]No synthesis_complete events found[/yellow]")
        return

    # Calculate queue wait by joining events
    queued = df[df["event_type"] == "synthesis_queued"].copy()
    started = df[df["event_type"] == "synthesis_started"].copy()

    console.print(
        Panel(
            "[cyan]Latency definitions:[/cyan]\n"
            "  • Queue wait: Time in Redis queue (queued → started)\n"
            "  • Worker time: TTS synthesis (started → complete)\n"
            "  • Total: Full request latency (queue wait + worker)",
            title="Latency Metrics",
            box=box.ROUNDED,
        )
    )

    table = Table(title="Latency by Model (ms)", box=box.ROUNDED)
    table.add_column("Model", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("P50 Worker", justify="right")
    table.add_column("P95 Worker", justify="right")
    table.add_column("P50 Queue Wait", justify="right")
    table.add_column("P95 Queue Wait", justify="right")

    for model in synthesis["model_slug"].dropna().unique():
        model_synthesis = synthesis[synthesis["model_slug"] == model]
        worker = model_synthesis["worker_latency_ms"].dropna()

        # Calculate queue wait for this model
        model_queued = queued[queued["model_slug"] == model]
        model_started = started[started["model_slug"] == model]

        queue_wait = pd.Series(dtype=float)
        if not model_queued.empty and not model_started.empty:
            qt = model_queued.set_index("variant_hash")["timestamp"]
            st = model_started.set_index("variant_hash")["timestamp"]
            common = qt.index.intersection(st.index)
            if len(common) > 0:
                queue_wait = (st[common] - qt[common]).dt.total_seconds() * 1000

        if worker.empty:
            continue

        table.add_row(
            model,
            str(len(model_synthesis)),
            f"{worker.quantile(0.5):.0f}",
            f"{worker.quantile(0.95):.0f}",
            f"{queue_wait.quantile(0.5):.0f}" if len(queue_wait) > 0 else "-",
            f"{queue_wait.quantile(0.95):.0f}" if len(queue_wait) > 0 else "-",
        )

    console.print(table)


def print_queue_stats(df: pd.DataFrame, console: Console) -> None:
    queued = df[df["event_type"] == "synthesis_queued"]

    if queued.empty:
        return

    depths = queued["queue_depth"].dropna()
    if not depths.empty:
        console.print(
            Panel(
                f"[cyan]Queue Depth (at enqueue time)[/cyan]\n"
                f"  Mean: {depths.mean():.1f}  Max: {depths.max():.0f}  "
                f"P95: {depths.quantile(0.95):.0f}",
                title="Queue Stats",
                box=box.ROUNDED,
            )
        )

    overflow_count = len(queued[queued["processor_route"] == "overflow"])
    local_count = len(queued[queued["processor_route"] == "local"])
    if overflow_count > 0:
        pct = overflow_count / (overflow_count + local_count) * 100
        console.print(f"[yellow]Overflow usage: {overflow_count} requests ({pct:.1f}%)[/yellow]")


def print_eviction_stats(df: pd.DataFrame, console: Console) -> None:
    triggered = df[df["event_type"] == "eviction_triggered"]
    skipped = df[df["event_type"] == "eviction_skipped"]

    if triggered.empty and skipped.empty:
        return

    console.print(
        Panel(
            f"[cyan]Eviction Events[/cyan]\n  Triggered: {len(triggered)}  Skipped jobs: {len(skipped)}",
            title="Eviction",
            box=box.ROUNDED,
        )
    )


MARKERS = ["o", "s", "^", "D", "v", "p", "*", "h"]  # Distinct shapes for models


def plot_synthesis_scatter(df: pd.DataFrame, output_dir: Path) -> Path | None:
    """Scatter plots for synthesis performance."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    if synthesis.empty or len(synthesis) < 2:
        return None

    synthesis = synthesis.dropna(subset=["text_length", "worker_latency_ms"])
    if synthesis.empty:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Synthesis Performance", fontsize=12)

    models = list(synthesis["model_slug"].dropna().unique())

    # Left: worker time over time (color=text_length)
    scatter = None
    for i, model in enumerate(models):
        model_data = synthesis[synthesis["model_slug"] == model]
        marker = MARKERS[i % len(MARKERS)]
        scatter = axes[0].scatter(
            model_data["local_time"],
            model_data["worker_latency_ms"],
            c=model_data["text_length"],
            cmap="plasma",
            alpha=0.7,
            label=model,
            s=40,
            marker=marker,
            edgecolors="white",
            linewidths=0.5,
        )

    axes[0].set_xlabel("Time")
    axes[0].set_ylabel("Worker Time (ms)")
    axes[0].set_title("Worker Time Over Time (color = text length)")
    axes[0].legend()
    axes[0].tick_params(axis="x", rotation=45)

    if scatter:
        cbar = plt.colorbar(scatter, ax=axes[0])
        cbar.set_label("Text Length (chars)")

    # Right: text length over time
    for i, model in enumerate(models):
        model_data = synthesis[synthesis["model_slug"] == model]
        marker = MARKERS[i % len(MARKERS)]
        axes[1].scatter(
            model_data["local_time"],
            model_data["text_length"],
            alpha=0.7,
            label=model,
            s=40,
            marker=marker,
        )

    axes[1].set_xlabel("Time")
    axes[1].set_ylabel("Text Length (chars)")
    axes[1].set_title("Text Length Over Time")
    axes[1].legend()
    axes[1].tick_params(axis="x", rotation=45)

    plt.tight_layout()

    output_path = output_dir / "synthesis_scatter.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_synthesis_ratio(df: pd.DataFrame, output_dir: Path) -> Path | None:
    """Plot synthesis ratio (worker_time / audio_duration) - shows real-time factor."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    if synthesis.empty:
        return None

    synthesis = synthesis.dropna(subset=["worker_latency_ms", "audio_duration_ms"])
    synthesis = synthesis[synthesis["audio_duration_ms"] > 0]
    if synthesis.empty or len(synthesis) < 2:
        return None

    synthesis["ratio"] = synthesis["worker_latency_ms"] / synthesis["audio_duration_ms"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Synthesis Speed (ratio < 1 = faster than real-time)", fontsize=12)

    # Left: ratio over time
    axes[0].scatter(synthesis["local_time"], synthesis["ratio"], alpha=0.6, s=30)
    axes[0].axhline(y=1.0, color="red", linestyle="--", label="Real-time (1.0)")
    axes[0].set_xlabel("Time")
    axes[0].set_ylabel("Synthesis Ratio (worker / audio duration)")
    axes[0].set_title("Synthesis Speed Over Time")
    axes[0].legend()
    axes[0].tick_params(axis="x", rotation=45)

    # Right: ratio histogram
    axes[1].hist(synthesis["ratio"], bins=20, edgecolor="white", alpha=0.7)
    axes[1].axvline(x=1.0, color="red", linestyle="--", label="Real-time (1.0)")
    axes[1].axvline(
        x=synthesis["ratio"].median(), color="green", linestyle="-", label=f"Median: {synthesis['ratio'].median():.2f}"
    )
    axes[1].set_xlabel("Synthesis Ratio")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Synthesis Ratio Distribution")
    axes[1].legend()

    plt.tight_layout()

    output_path = output_dir / "synthesis_ratio.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_latency_breakdown(df: pd.DataFrame, output_dir: Path) -> Path | None:
    """Stacked bar/area showing queue wait vs worker time."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    queued = df[df["event_type"] == "synthesis_queued"].copy()
    started = df[df["event_type"] == "synthesis_started"].copy()

    if synthesis.empty or queued.empty or started.empty:
        return None

    # Calculate queue wait per job
    qt = queued.set_index("variant_hash")["timestamp"]
    st = started.set_index("variant_hash")["timestamp"]
    common = qt.index.intersection(st.index)
    if len(common) < 2:
        return None

    queue_wait = (st[common] - qt[common]).dt.total_seconds() * 1000
    queue_wait_df = pd.DataFrame(
        {
            "variant_hash": list(common),
            "calc_queue_wait_ms": queue_wait.values,
        }
    )

    # Merge with synthesis data
    merged = synthesis.merge(queue_wait_df, on="variant_hash", how="inner")
    if merged.empty or "calc_queue_wait_ms" not in merged.columns:
        return None

    merged = merged.sort_values("local_time").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12, 5))

    # Stacked area
    queue_wait_vals = merged["calc_queue_wait_ms"].values
    worker_vals = merged["worker_latency_ms"].values

    ax.fill_between(range(len(merged)), 0, queue_wait_vals, alpha=0.7, label="Queue Wait")
    ax.fill_between(range(len(merged)), queue_wait_vals, queue_wait_vals + worker_vals, alpha=0.7, label="Worker Time")

    ax.set_xlabel("Request (chronological)")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Latency Breakdown: Queue Wait + Worker Time")
    ax.legend()

    plt.tight_layout()

    output_path = output_dir / "latency_breakdown.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_model_usage(df: pd.DataFrame, output_dir: Path) -> Path | None:
    """Bar chart showing synthesis counts by model and route."""
    # Get synthesis events (queued has model + route info)
    queued = df[df["event_type"] == "synthesis_queued"].copy()
    cache_hits = df[df["event_type"] == "cache_hit"].copy()

    if queued.empty and cache_hits.empty:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Model & Route Usage", fontsize=12)

    # Left: by model
    model_counts = queued["model_slug"].value_counts()
    cache_by_model = cache_hits["model_slug"].value_counts()

    if not model_counts.empty:
        models = list(set(model_counts.index) | set(cache_by_model.index))
        synth_vals = [model_counts.get(m, 0) for m in models]
        cache_vals = [cache_by_model.get(m, 0) for m in models]

        x = range(len(models))
        width = 0.35
        axes[0].bar([i - width / 2 for i in x], synth_vals, width, label="Synthesized")
        axes[0].bar([i + width / 2 for i in x], cache_vals, width, label="Cache Hit")
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(models, rotation=45, ha="right")
        axes[0].set_ylabel("Count")
        axes[0].set_title("Requests by Model")
        axes[0].legend()

    # Right: by route (local vs overflow)
    route_counts = queued["processor_route"].value_counts()
    if not route_counts.empty and route_counts.sum() > 0:
        colors = ["#2ecc71" if r == "local" else "#e74c3c" for r in route_counts.index]
        axes[1].bar(route_counts.index, route_counts.values, color=colors)
        axes[1].set_ylabel("Count")
        axes[1].set_title("Requests by Route (local vs overflow)")

        # Add percentage labels
        total = route_counts.sum()
        for i, (route, count) in enumerate(route_counts.items()):
            pct = count / total * 100
            axes[1].text(i, count + 0.5, f"{pct:.1f}%", ha="center")
    else:
        axes[1].text(0.5, 0.5, "No route data", ha="center", va="center", transform=axes[1].transAxes)
        axes[1].set_title("Requests by Route")

    plt.tight_layout()

    output_path = output_dir / "model_usage.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_queue_metrics(df: pd.DataFrame, output_dir: Path) -> Path | None:
    """Queue depth and wait time over time."""
    queued = df[df["event_type"] == "synthesis_queued"].copy()
    started = df[df["event_type"] == "synthesis_started"].copy()

    if queued.empty:
        return None

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle("Queue Metrics", fontsize=12)

    # Queue depth over time
    if "queue_depth" in queued.columns:
        axes[0].scatter(queued["local_time"], queued["queue_depth"], alpha=0.5, s=20)
        axes[0].set_ylabel("Queue Depth")
        axes[0].set_title("Queue Depth at Enqueue Time (how many jobs ahead in queue)")

    # Queue wait time
    if not started.empty:
        queued_times = queued.set_index("variant_hash")["timestamp"]
        started_times = started.set_index("variant_hash")["timestamp"]
        started_local = started.set_index("variant_hash")["local_time"]
        common = queued_times.index.intersection(started_times.index)

        if len(common) > 0:
            wait_times = (started_times[common] - queued_times[common]).dt.total_seconds() * 1000
            axes[1].scatter(started_local[common], wait_times, alpha=0.5, s=20)
            axes[1].set_ylabel("Queue Wait (ms)")
            axes[1].set_title("Queue Wait Time (time spent waiting in Redis queue)")

    axes[1].set_xlabel("Time")
    axes[1].tick_params(axis="x", rotation=45)

    plt.tight_layout()

    output_path = output_dir / "queue_metrics.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def open_file(path: Path) -> None:
    """Open file with system default viewer."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True)
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(path)], check=True, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["start", str(path)], shell=True, check=True)
    except Exception:
        pass  # Silently fail if can't open


def main(
    db: Path = Path("metrics/metrics.db"),
    since: str = "24 hours",
    plot: bool = False,
    model: str | None = None,
    output_dir: Path = Path("metrics/plots"),
) -> None:
    """Analyze metrics with sensible defaults.

    Args:
        db: Path to metrics SQLite database.
        since: Time filter: '1 hour', '7 days', '2025-01-05 10:00', etc.
        plot: Generate plots (saved to output_dir and opened).
        model: Filter to specific model slug.
        output_dir: Where to save plots.
    """
    console = Console()

    try:
        since_dt = parse_since(since)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    console.print(f"[dim]Analyzing metrics since {since_dt.strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n")

    conn = get_db_connection(db)
    df = load_events(conn, since_dt)
    conn.close()

    if df.empty:
        console.print("[yellow]No events found in time range[/yellow]")
        return

    if model:
        df = df[df["model_slug"] == model]
        if df.empty:
            console.print(f"[yellow]No events found for model: {model}[/yellow]")
            return

    print_health_summary(df, console)
    console.print()
    print_latency_stats(df, console)
    console.print()
    print_queue_stats(df, console)
    console.print()
    print_eviction_stats(df, console)

    if plot:
        output_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"\n[dim]Generating plots in {output_dir}/[/dim]")

        paths = []
        if p := plot_synthesis_scatter(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")
        if p := plot_synthesis_ratio(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")
        if p := plot_latency_breakdown(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")
        if p := plot_model_usage(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")
        if p := plot_queue_metrics(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")

        # Open the first plot
        if paths:
            open_file(paths[0])


if __name__ == "__main__":
    tyro.cli(main)
