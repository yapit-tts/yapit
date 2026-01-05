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
from datetime import datetime, timedelta
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
    """Parse relative or absolute time string."""
    since = since.strip().lower()
    now = datetime.now()

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
    """Scatter: text_length vs worker_time, colored by time, shaped by model."""
    synthesis = df[df["event_type"] == "synthesis_complete"].copy()
    if synthesis.empty or len(synthesis) < 2:
        return None

    synthesis = synthesis.dropna(subset=["text_length", "worker_latency_ms"])
    if synthesis.empty:
        return None

    t_min = synthesis["timestamp"].min()
    t_max = synthesis["timestamp"].max()
    if t_min == t_max:
        synthesis["time_norm"] = 0.5
    else:
        synthesis["time_norm"] = (synthesis["timestamp"] - t_min) / (t_max - t_min)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Synthesis Performance (Worker Time = actual TTS processing)", fontsize=12)

    models = list(synthesis["model_slug"].dropna().unique())

    # Left: text_length vs worker_latency (color=time, marker=model)
    scatter = None
    for i, model in enumerate(models):
        model_data = synthesis[synthesis["model_slug"] == model]
        marker = MARKERS[i % len(MARKERS)]
        scatter = axes[0].scatter(
            model_data["text_length"],
            model_data["worker_latency_ms"],
            c=model_data["time_norm"],
            cmap="viridis",
            alpha=0.7,
            label=model,
            s=40,
            marker=marker,
            edgecolors="white",
            linewidths=0.5,
        )

    axes[0].set_xlabel("Text Length (chars)")
    axes[0].set_ylabel("Worker Time (ms)")
    axes[0].set_title("Text Length vs Worker Time")
    axes[0].legend()

    if scatter:
        cbar = plt.colorbar(scatter, ax=axes[0])
        cbar.set_label(f"Time ({t_min.strftime('%H:%M')} → {t_max.strftime('%H:%M')})")

    # Right: latency over time (marker=model, color=model for clarity here)
    for i, model in enumerate(models):
        model_data = synthesis[synthesis["model_slug"] == model]
        marker = MARKERS[i % len(MARKERS)]
        axes[1].scatter(
            model_data["local_time"],
            model_data["worker_latency_ms"],
            alpha=0.7,
            label=model,
            s=40,
            marker=marker,
        )

    axes[1].set_xlabel("Time")
    axes[1].set_ylabel("Worker Time (ms)")
    axes[1].set_title("Worker Time Over Time")
    axes[1].legend()
    axes[1].tick_params(axis="x", rotation=45)

    plt.tight_layout()

    output_path = output_dir / "synthesis_scatter.png"
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
        if p := plot_queue_metrics(df, output_dir):
            paths.append(p)
            console.print(f"  Saved: {p}")

        # Open the first plot
        if paths:
            open_file(paths[0])


if __name__ == "__main__":
    tyro.cli(main)
