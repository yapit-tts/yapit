# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "python-dotenv"]
# ///
"""Proxy diagnostics — Stack Auth + Traefik summary from prod container logs.

SSHes into the VPS, pulls recent container logs, and outputs a compact
diagnostic summary. Designed for the daily report agent (--plain by default)
but also useful for ad-hoc debugging.

Requires VPS_HOST in .env and SSH access (Tailscale).

Examples::

    uv run scripts/proxy_diagnostics.py
    uv run scripts/proxy_diagnostics.py --hours 4
    uv run scripts/proxy_diagnostics.py --section traefik
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tyro
from dotenv import load_dotenv

Section = Literal["all", "stack-auth", "traefik"]


@dataclass
class Args:
    hours: int = 24
    """Time window (hours back from now)."""
    section: Section = "all"
    """Which section to show."""
    plain: bool = True
    """Plain output for LLM consumption (default). Use --no-plain for human-friendly."""


def ssh_cmd(host: str, cmd: str) -> str:
    result = subprocess.run(
        ["ssh", host, cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"SSH error: {result.stderr.strip()}", file=sys.stderr)
    return result.stdout


def parse_stack_auth(host: str, hours: int) -> dict:
    raw = ssh_cmd(host, f"docker logs $(docker ps -q -f name=yapit_stack-auth) --since {hours}h 2>&1")
    if not raw.strip():
        return {"error": "no output from Stack Auth container"}

    response_times: list[int] = []
    status_counts: dict[int, int] = defaultdict(int)
    errors: dict[str, int] = defaultdict(int)
    slow: list[tuple[int, int, str, str]] = []

    for line in raw.splitlines():
        # Response lines: [    RES] [...] METHOD url: STATUS (in Xms)
        m = re.search(r"\[\s+RES\].*?(\w+)\s+(https?://\S+):\s+(\d+)\s+\(in\s+(\d+)ms\)", line)
        if m:
            method, url, status, ms = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            response_times.append(ms)
            status_counts[status] += 1
            if ms > 1000:
                path = url.split("0.0.0.0:8102")[-1] if "0.0.0.0:8102" in url else url
                slow.append((ms, status, method, path[:80]))
            continue

        # Error lines
        m2 = re.search(r"Captured error.*?:\s+(.*)", line)
        if m2:
            errors[m2.group(1)[:80]] += 1

    if not response_times:
        return {"error": "no response lines found in Stack Auth logs"}

    response_times.sort()
    n = len(response_times)
    return {
        "requests": n,
        "p50": response_times[n // 2],
        "p95": response_times[int(n * 0.95)],
        "p99": response_times[int(n * 0.99)],
        "max": response_times[-1],
        "status_counts": dict(sorted(status_counts.items())),
        "slow_requests": sorted(slow, reverse=True)[:10],
        "errors": dict(sorted(errors.items(), key=lambda x: -x[1])),
    }


def parse_traefik(host: str, hours: int) -> dict:
    raw = ssh_cmd(host, f"docker logs traefik --since {hours}h 2>&1")
    if not raw.strip():
        return {"error": "no output from Traefik container"}

    total = 0
    status_counts: dict[int, int] = defaultdict(int)
    by_service: dict[str, list[float]] = defaultdict(list)
    slow: list[tuple[float, int, str, str, str]] = []
    errors_5xx: list[tuple[int, str, str, float]] = []

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

        total += 1
        status_counts[status] += 1

        # Status 0 = WebSocket (open connection, duration is lifetime). Exclude from latency stats.
        if status != 0:
            by_service[service].append(duration_ms)

        if duration_ms > 5000 and status != 0:
            slow.append((duration_ms, status, method, path[:60], service))

        if 500 <= status <= 599:
            errors_5xx.append((status, method, path[:60], duration_ms))

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


def print_stack_auth(data: dict, plain: bool) -> None:
    if "error" in data:
        print(f"  Stack Auth: {data['error']}")
        return

    header = "# Stack Auth" if plain else "Stack Auth"
    print(header)
    if not plain:
        print("─" * 50)

    print(
        f"  requests={data['requests']} p50={data['p50']}ms p95={data['p95']}ms p99={data['p99']}ms max={data['max']}ms"
    )

    if data["status_counts"]:
        codes = " ".join(f"{s}:{c}" for s, c in data["status_counts"].items())
        print(f"  status: {codes}")

    for msg, count in data["errors"].items():
        print(f"  error: {count}x {msg}")

    for ms, status, method, path in data["slow_requests"]:
        print(f"  slow: {ms}ms {status} {method} {path}")

    print()


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

    for status, method, path, ms in data["errors_5xx"]:
        print(f"  5xx: {status} {method} {path} ({ms:.0f}ms)")

    for ms, status, method, path, svc in data["slow_requests"]:
        print(f"  slow: {ms:.0f}ms {status} {method} {path} [{svc}]")

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

    if args.section in ("all", "stack-auth"):
        data = parse_stack_auth(host, args.hours)
        print_stack_auth(data, args.plain)

    if args.section in ("all", "traefik"):
        data = parse_traefik(host, args.hours)
        print_traefik(data, args.plain)


if __name__ == "__main__":
    main(tyro.cli(Args, description=__doc__))
