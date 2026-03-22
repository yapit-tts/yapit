#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["psycopg", "python-dotenv", "tyro"]
# ///
"""Guest user stats and storage audit.

Shows document counts, storage usage, and activity recency for guest (anonymous)
vs registered users. Useful for monitoring guest user growth and identifying
candidates for TTL cleanup.

Runs locally via SSH into the gateway container (needs VPS_HOST in .env),
or directly inside the container when DATABASE_URL is set.

Examples::

    uv run scripts/guest_users.py
    uv run scripts/guest_users.py --inactive 30
    uv run scripts/guest_users.py --top 20
    uv run scripts/guest_users.py --inactive 30 --json
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Args:
    inactive: int | None = None
    """Only show guest users inactive for more than N days."""
    top: int | None = None
    """Limit output to top N guest users by storage."""
    json: bool = False
    """Output as JSON."""


def format_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


def run_local(args: Args) -> int:
    import psycopg
    from psycopg.rows import dict_row

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        return 1

    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    CASE WHEN user_id LIKE 'anon-%%' THEN 'guest' ELSE 'registered' END AS user_type,
                    COUNT(DISTINCT user_id) AS users,
                    COUNT(*) AS documents,
                    COALESCE(SUM(LENGTH(original_text) + LENGTH(structured_content)), 0) AS storage_bytes,
                    MIN(created) AS earliest,
                    MAX(created) AS latest
                FROM document
                GROUP BY 1
                ORDER BY 1
            """)
            summary = cur.fetchall()

            cur.execute("""
                SELECT
                    user_id,
                    COUNT(*) AS doc_count,
                    COALESCE(SUM(LENGTH(original_text) + LENGTH(structured_content)), 0) AS storage_bytes,
                    MIN(created) AS first_doc,
                    MAX(COALESCE(last_played_at, created)) AS last_activity
                FROM document
                WHERE user_id LIKE 'anon-%%'
                GROUP BY user_id
                ORDER BY storage_bytes DESC
            """)
            guests = cur.fetchall()

    now = datetime.now(timezone.utc)

    if args.json:
        return _output_json(summary, guests, now, args)

    print("=== User Type Breakdown ===")
    print(f"{'Type':<12} {'Users':>8} {'Docs':>8} {'Storage':>12} {'Earliest':<12} {'Latest':<12}")
    print("-" * 68)
    for row in summary:
        print(
            f"{row['user_type']:<12} {row['users']:>8} {row['documents']:>8} "
            f"{format_bytes(row['storage_bytes']):>12} "
            f"{row['earliest'].strftime('%Y-%m-%d'):<12} {row['latest'].strftime('%Y-%m-%d'):<12}"
        )

    if not guests:
        print("\nNo guest users found.")
        return 0

    if args.inactive:
        guests = [g for g in guests if (now - g["last_activity"].replace(tzinfo=timezone.utc)).days > args.inactive]
        print(f"\n=== Guest Users Inactive >{args.inactive} Days ({len(guests)}) ===")
    else:
        print(f"\n=== Guest Users ({len(guests)} total) ===")

    display = guests[: args.top] if args.top else guests

    print(f"{'User ID':<44} {'Docs':>5} {'Storage':>10} {'Last Active':<12} {'Idle':>6}")
    print("-" * 82)
    for g in display:
        last = g["last_activity"].replace(tzinfo=timezone.utc)
        idle_days = (now - last).days
        print(
            f"{g['user_id'][:43]:<44} {g['doc_count']:>5} "
            f"{format_bytes(g['storage_bytes']):>10} "
            f"{last.strftime('%Y-%m-%d'):<12} {idle_days:>4}d"
        )

    if args.top and len(guests) > args.top:
        print(f"  ... and {len(guests) - args.top} more")

    total_storage = sum(g["storage_bytes"] for g in guests)
    total_docs = sum(g["doc_count"] for g in guests)
    print(f"\nTotal: {len(guests)} guest users, {total_docs} docs, {format_bytes(total_storage)}")

    return 0


def _output_json(summary, guests, now, args: Args):
    if args.inactive:
        guests = [g for g in guests if (now - g["last_activity"].replace(tzinfo=timezone.utc)).days > args.inactive]

    output = {
        "summary": [
            {
                "user_type": r["user_type"],
                "users": r["users"],
                "documents": r["documents"],
                "storage_bytes": r["storage_bytes"],
            }
            for r in summary
        ],
        "guests": [
            {
                "user_id": g["user_id"],
                "doc_count": g["doc_count"],
                "storage_bytes": g["storage_bytes"],
                "last_activity": g["last_activity"].isoformat(),
                "idle_days": (now - g["last_activity"].replace(tzinfo=timezone.utc)).days,
            }
            for g in (guests[: args.top] if args.top else guests)
        ],
        "totals": {
            "guest_users": len(guests),
            "guest_docs": sum(g["doc_count"] for g in guests),
            "guest_storage_bytes": sum(g["storage_bytes"] for g in guests),
        },
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


def run_remote(vps_host: str, args: list[str]) -> int:
    script_content = Path(__file__).read_text()
    remote_cmd = f'docker exec -i $(docker ps -qf "name=yapit_gateway") python - {" ".join(args)}'
    result = subprocess.run(["ssh", vps_host, remote_cmd], input=script_content, text=True)
    return result.returncode


def _parse_container_argv() -> Args:
    """Minimal argv parser for container mode (tyro may not be installed)."""
    args = Args()
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--inactive" and i + 1 < len(argv):
            args.inactive = int(argv[i + 1])
            i += 2
        elif argv[i] == "--top" and i + 1 < len(argv):
            args.top = int(argv[i + 1])
            i += 2
        elif argv[i] == "--json":
            args.json = True
            i += 1
        else:
            i += 1
    return args


def main():
    # Inside container: tyro may not be on the path, parse argv directly
    if os.environ.get("DATABASE_URL"):
        return run_local(_parse_container_argv())

    import tyro
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    args = tyro.cli(Args, description=__doc__)

    vps_host = os.environ.get("VPS_HOST")
    if not vps_host:
        print("Error: VPS_HOST not set (e.g., yapit-prod)", file=sys.stderr)
        return 1

    remote_args = []
    if args.inactive is not None:
        remote_args.extend(["--inactive", str(args.inactive)])
    if args.top is not None:
        remote_args.extend(["--top", str(args.top)])
    if args.json:
        remote_args.append("--json")

    return run_remote(vps_host, remote_args)


if __name__ == "__main__":
    sys.exit(main())
