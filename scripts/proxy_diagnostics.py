# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "python-dotenv"]
# ///
"""Proxy diagnostics — Traefik summary from prod container logs.

SSHes into the VPS, pulls recent container logs, and outputs a compact
diagnostic summary. Designed for the daily report agent (--plain by default)
but also useful for ad-hoc debugging.

Requires VPS_HOST in .env and SSH access (Tailscale).

Examples:
    uv run scripts/proxy_diagnostics.py
    uv run scripts/proxy_diagnostics.py --hours 4
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import tyro
from dotenv import load_dotenv


@dataclass
class Args:
    hours: int = 24
    """Time window (hours back from now)."""
    plain: bool = True
    """Plain output for LLM consumption (default). Use --no-plain for human-friendly."""


def ssh_cmd(host: str, cmd: str) -> str:
    result = subprocess.run(
        ["ssh", host, cmd],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        print(f"SSH error: {result.stderr.strip()}", file=sys.stderr)
    return result.stdout


def _when(iso: str) -> str:
    """RFC3339 timestamp → 'MM-DD HH:MM' UTC, enough to line an entry up with gateway.jsonl."""
    return iso[5:16].replace("T", " ")


def parse_traefik(host: str, hours: int) -> dict:
    raw = ssh_cmd(host, f"docker logs traefik --since {hours}h 2>&1")
    if not raw.strip():
        return {"error": "no output from Traefik container"}

    total = 0
    status_counts: dict[int, int] = defaultdict(int)
    by_service: dict[str, list[float]] = defaultdict(list)
    slow: list[tuple[float, int, str, str, str, str]] = []
    errors_5xx: list[tuple[int, str, str, float, str]] = []

    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        status = r.get("DownstreamStatus", 0)
        duration_ns = r.get("Duration", 0)
        duration_ms = duration_ns / 1_000_000
        service = r.get("ServiceName", "unknown")
        method = r.get("RequestMethod", "?")
        path = r.get("RequestPath", "?")
        when = _when(r.get("StartUTC", ""))

        total += 1
        status_counts[status] += 1

        # Status 0 = WebSocket (open connection, duration is lifetime). Exclude from latency stats.
        if status != 0:
            by_service[service].append(duration_ms)

        if duration_ms > 5000 and status != 0:
            slow.append((duration_ms, status, method, path[:60], service, when))

        if 500 <= status <= 599:
            errors_5xx.append((status, method, path[:60], duration_ms, when))

    if not total:
        return {"error": "no JSON log lines found in Traefik logs"}

    # Service latency summary
    service_summary = {}
    for svc, times in sorted(by_service.items()):
        times.sort()
        n = len(times)
        if n == 0:
            continue
        service_summary[svc] = {
            "count": n,
            "p50": round(times[n // 2], 1),
            "p95": round(times[int(n * 0.95)], 1),
            "p99": round(times[int(n * 0.99)], 1),
            "max": round(times[-1], 1),
        }

    return {
        "total": total,
        "status_counts": dict(sorted(status_counts.items())),
        "by_service": service_summary,
        "slow_requests": sorted(slow, reverse=True)[:10],
        "errors_5xx": errors_5xx[:20],
    }


def print_traefik(data: dict, plain: bool) -> None:
    if "error" in data:
        print(f"  Traefik: {data['error']}")
        return

    header = "# Traefik" if plain else "Traefik"
    print(header)
    if not plain:
        print("─" * 50)

    codes = " ".join(f"{s}:{c}" for s, c in data["status_counts"].items())
    print(f"  requests={data['total']} status: {codes}")

    print("  service latency:")
    for svc, stats in data["by_service"].items():
        print(
            f"    {svc}: n={stats['count']} p50={stats['p50']}ms p95={stats['p95']}ms p99={stats['p99']}ms max={stats['max']}ms"
        )

    for status, method, path, ms, when in data["errors_5xx"]:
        print(f"  5xx: {when}Z {status} {method} {path} ({ms:.0f}ms)")

    for ms, status, method, path, svc, when in data["slow_requests"]:
        print(f"  slow: {when}Z {ms:.0f}ms {status} {method} {path} [{svc}]")

    print()


def main(args: Args) -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    host = os.environ.get("VPS_HOST")
    if not host:
        print("VPS_HOST not set in .env", file=sys.stderr)
        sys.exit(1)

    window = f"{args.hours}h" if args.hours < 48 else f"{args.hours // 24}d"
    if args.plain:
        print(f"Proxy Diagnostics last {window}")
    else:
        print(f"\nProxy Diagnostics — last {window}")
    print()

    print_traefik(parse_traefik(host, args.hours), args.plain)


if __name__ == "__main__":
    main(tyro.cli(Args, description=__doc__))
