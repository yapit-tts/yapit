# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "httpx", "python-dotenv"]
# ///
"""Cloudflare analytics for yapit.md — traffic, cache, errors, DNS.

Pulls data from the CF GraphQL Analytics API (free plan compatible).
Reads CLOUDFLARE_API_TOKEN from .env (run `make prod-env` first).

Examples::

    uv run scripts/cf_analytics.py
    uv run scripts/cf_analytics.py --hours 168
    uv run scripts/cf_analytics.py --section cache
    uv run scripts/cf_analytics.py --section errors --hours 24
    uv run scripts/cf_analytics.py --section 504
    uv run scripts/cf_analytics.py --json
"""

from __future__ import annotations

import json as json_mod
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
import tyro
from dotenv import load_dotenv

ZONE_ID = "e307c22342c2d1dada1d4d45da3e1bce"
GQL_URL = "https://api.cloudflare.com/client/v4/graphql"

PLAIN = False

Section = Literal["all", "overview", "cache", "errors", "504", "paths", "countries", "dns", "hourly"]


@dataclass
class Args:
    hours: int = 24
    """Time window to query (hours back from now). Adaptive queries limited to 24h on free plan."""
    section: Section = "all"
    """Which section to show. 'all' shows everything."""
    json: bool = False
    """Output raw JSON instead of formatted text."""
    plain: bool = False
    """Machine-friendly output — no bars, no unicode, compact TSV-like format. Ideal for piping to LLMs."""
    top_n: int = 10
    """Number of items in top-N lists (paths, countries, etc.)."""


def gql(token: str, query: str) -> dict[str, Any]:
    r = httpx.post(
        GQL_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        msgs = [e["message"] for e in data["errors"]]
        print(f"GraphQL errors: {msgs}", file=sys.stderr)
        sys.exit(1)
    return data["data"]["viewer"]["zones"][0]


def build_query(zone_id: str, start: str, end: str, top_n: int) -> str:
    f = f'datetime_geq: "{start}", datetime_leq: "{end}"'
    return f"""{{
  viewer {{
    zones(filter: {{zoneTag: "{zone_id}"}}) {{
      daily: httpRequests1dGroups(
        limit: 30
        filter: {{date_geq: "{start[:10]}", date_leq: "{end[:10]}"}}
        orderBy: [date_ASC]
      ) {{
        sum {{ requests cachedRequests bytes cachedBytes threats pageViews }}
        uniq {{ uniques }}
        dimensions {{ date }}
      }}
      cacheStatus: httpRequestsAdaptiveGroups(
        limit: {top_n}, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ cacheStatus }} }}
      statusCodes: httpRequestsAdaptiveGroups(
        limit: 20, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ edgeResponseStatus }} }}
      topPaths: httpRequestsAdaptiveGroups(
        limit: {top_n}, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ clientRequestPath }} }}
      countries: httpRequestsAdaptiveGroups(
        limit: {top_n}, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ clientCountryName }} }}
      httpVersions: httpRequestsAdaptiveGroups(
        limit: 5, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ clientRequestHTTPProtocol }} }}
      errors5xx: httpRequestsAdaptiveGroups(
        limit: {top_n}
        filter: {{{f}, edgeResponseStatus_geq: 500}}
        orderBy: [count_DESC]
      ) {{ count dimensions {{ clientRequestPath edgeResponseStatus }} }}
      errors4xx: httpRequestsAdaptiveGroups(
        limit: {top_n}
        filter: {{{f}, edgeResponseStatus_geq: 400, edgeResponseStatus_lt: 500}}
        orderBy: [count_DESC]
      ) {{ count dimensions {{ clientRequestPath edgeResponseStatus }} }}
      hourly: httpRequestsAdaptiveGroups(
        limit: 200
        filter: {{{f}}}
        orderBy: [datetimeHour_ASC]
      ) {{ count sum {{ edgeResponseBytes }} dimensions {{ datetimeHour }} }}
      hourly5xx: httpRequestsAdaptiveGroups(
        limit: 200
        filter: {{{f}, edgeResponseStatus_geq: 500}}
        orderBy: [datetimeHour_ASC]
      ) {{ count dimensions {{ datetimeHour }} }}
      dns: dnsAnalyticsAdaptiveGroups(
        limit: {top_n}, filter: {{{f}}}, orderBy: [count_DESC]
      ) {{ count dimensions {{ queryName responseCode }} }}
      err504byOrigin: httpRequestsAdaptiveGroups(
        limit: 5
        filter: {{{f}, edgeResponseStatus: 504}}
        orderBy: [count_DESC]
      ) {{ count dimensions {{ originResponseStatus }} }}
      err504byHost: httpRequestsAdaptiveGroups(
        limit: 10
        filter: {{{f}, edgeResponseStatus: 504}}
        orderBy: [count_DESC]
      ) {{ count dimensions {{ clientRequestHTTPHost clientRequestPath }} }}
      err504byIP: httpRequestsAdaptiveGroups(
        limit: 10
        filter: {{{f}, edgeResponseStatus: 504}}
        orderBy: [count_DESC]
      ) {{ count dimensions {{ clientIP clientCountryName }} }}
    }}
  }}
}}"""


def fmt_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024**2:
        return f"{b / 1024:.1f} KB"
    if b < 1024**3:
        return f"{b / 1024**2:.2f} MB"
    return f"{b / 1024**3:.2f} GB"


def pct(part: int, total: int) -> str:
    return f"{part / total * 100:.1f}%" if total else "0%"


def bar(value: int, max_value: int, width: int = 20) -> str:
    filled = round(value / max_value * width) if max_value else 0
    return "█" * filled + "░" * (width - filled)


def heading(title: str) -> None:
    if PLAIN:
        print(f"\n# {title}")
    else:
        print(title)
        print("─" * 50)


def print_table(rows: list[tuple[str, int]], total: int | None = None) -> None:
    if not rows:
        print("  (no data)")
        return
    if PLAIN:
        for label, value in rows:
            pct_str = f"\t{pct(value, total)}" if total else ""
            print(f"{label}\t{value}{pct_str}")
        return
    max_val = max(v for _, v in rows)
    max_label = max(len(label) for label, _ in rows)
    for label, value in rows:
        pct_str = f"  ({pct(value, total)})" if total else ""
        print(f"  {label:<{max_label}}  {value:>6}  {bar(value, max_val)}{pct_str}")


def print_overview(data: dict[str, Any]) -> None:
    daily = data["daily"]
    total_req = sum(d["sum"]["requests"] for d in daily)
    cached_req = sum(d["sum"]["cachedRequests"] for d in daily)
    total_bw = sum(d["sum"]["bytes"] for d in daily)
    cached_bw = sum(d["sum"]["cachedBytes"] for d in daily)
    threats = sum(d["sum"]["threats"] for d in daily)
    uniques = sum(d["uniq"]["uniques"] for d in daily)
    page_views = sum(d["sum"]["pageViews"] for d in daily)

    total_5xx = sum(d["count"] for d in data["statusCodes"] if d["dimensions"]["edgeResponseStatus"] >= 500)
    total_504 = sum(d["count"] for d in data["err504byOrigin"])
    origin_never = sum(d["count"] for d in data["err504byOrigin"] if d["dimensions"]["originResponseStatus"] == 0)

    heading("Overview")
    print(
        f"  requests={total_req} cached={cached_req}({pct(cached_req, total_req)}) bandwidth={fmt_bytes(total_bw)} cached_bw={fmt_bytes(cached_bw)}({pct(cached_bw, total_bw)})"
        if PLAIN
        else f"  Requests:        {total_req:,}  (cached: {cached_req:,} / {pct(cached_req, total_req)})\n"
        f"  Bandwidth:       {fmt_bytes(total_bw)}  (cached: {fmt_bytes(cached_bw)} / {pct(cached_bw, total_bw)})"
    )
    print(
        f"  uniques={uniques} pageviews={page_views} threats={threats} 5xx={total_5xx} 504={total_504} 504_origin_unreachable={origin_never}"
        if PLAIN
        else f"  Unique visitors: {uniques:,}\n"
        f"  Page views:      {page_views:,}\n"
        f"  Threats:         {threats:,}"
        + (
            f"\n  5xx errors:      {total_5xx:,}  (504s: {total_504}, origin-unreachable: {origin_never})"
            if total_5xx
            else ""
        )
    )
    print()

    versions = [(d["dimensions"]["clientRequestHTTPProtocol"], d["count"]) for d in data["httpVersions"]]
    heading("HTTP Versions")
    print_table(versions, total_req)
    print()


def print_cache(data: dict[str, Any]) -> None:
    rows = [(d["dimensions"]["cacheStatus"], d["count"]) for d in data["cacheStatus"]]
    total = sum(v for _, v in rows)
    heading("Cache Status")
    print_table(rows, total)

    hit = sum(v for k, v in rows if k in ("hit", "revalidated"))
    miss = sum(v for k, v in rows if k == "miss")
    dynamic = sum(v for k, v in rows if k == "dynamic")
    print(f"\n  Hit ratio (hit+revalidated / cacheable): {pct(hit, hit + miss) if (hit + miss) else 'n/a'}")
    print(f"  Dynamic (not cacheable): {dynamic:,} ({pct(dynamic, total)})")
    print()


def print_errors(data: dict[str, Any]) -> None:
    status_rows = [(str(d["dimensions"]["edgeResponseStatus"]), d["count"]) for d in data["statusCodes"]]
    total = sum(v for _, v in status_rows)
    heading("Status Codes")
    print_table(status_rows, total)
    print()

    err5 = data["errors5xx"]
    if err5:
        heading("5xx Errors (by path)")
        rows = [
            (f"{d['dimensions']['edgeResponseStatus']} {d['dimensions']['clientRequestPath']}", d["count"])
            for d in err5
        ]
        print_table(rows)
        print()

    err4 = data["errors4xx"]
    if err4:
        heading("4xx Errors (by path)")
        rows = [
            (f"{d['dimensions']['edgeResponseStatus']} {d['dimensions']['clientRequestPath']}", d["count"])
            for d in err4
        ]
        print_table(rows)
        print()


def print_504(data: dict[str, Any]) -> None:
    by_origin = data["err504byOrigin"]
    total_504 = sum(d["count"] for d in by_origin)
    if not total_504:
        heading("504 Diagnostics")
        print("  No 504 errors in this window.")
        print()
        return

    total_req = sum(d["count"] for d in data["statusCodes"])
    origin_never = sum(d["count"] for d in by_origin if d["dimensions"]["originResponseStatus"] == 0)

    heading("504 Diagnostics")
    if PLAIN:
        print(f"  total_504={total_504} pct={pct(total_504, total_req)} origin_unreachable={origin_never}")
        by_host = data["err504byHost"]
        for d in by_host:
            dims = d["dimensions"]
            print(f"  {d['count']}\t{dims['clientRequestHTTPHost']}{dims['clientRequestPath'][:60]}")
        by_ip = data["err504byIP"]
        for d in by_ip:
            dims = d["dimensions"]
            print(f"  {d['count']}\t{dims['clientIP']}\t{dims['clientCountryName']}")
        hourly5xx = data.get("hourly5xx", [])
        for d in hourly5xx:
            print(f"  {d['dimensions']['datetimeHour'][11:16]}\t{d['count']} 5xx")
        print()
        return

    print(f"  Total 504s: {total_504}  ({pct(total_504, total_req)} of all requests)")
    print()

    print("  Origin response status:")
    for d in by_origin:
        status = d["dimensions"]["originResponseStatus"]
        label = "origin unreachable (CF-generated)" if status == 0 else f"origin returned {status}"
        print(f"    {d['count']:>4}x  {label}")
    print()

    by_host = data["err504byHost"]
    if by_host:
        print("  By host/path:")
        for d in by_host:
            dims = d["dimensions"]
            print(f"    {d['count']:>4}x  {dims['clientRequestHTTPHost']}{dims['clientRequestPath'][:60]}")
        print()

    by_ip = data["err504byIP"]
    if by_ip:
        print("  By client IP:")
        for d in by_ip:
            dims = d["dimensions"]
            print(f"    {d['count']:>4}x  {dims['clientIP']}  ({dims['clientCountryName']})")
        print()

    hourly5xx = data.get("hourly5xx", [])
    if hourly5xx:
        print("  5xx by hour:")
        max_count = max(d["count"] for d in hourly5xx)
        for d in hourly5xx:
            hour = d["dimensions"]["datetimeHour"][11:16]
            print(f"    {hour}  {d['count']:>4}  {bar(d['count'], max_count, 25)}")
        print()


def print_paths(data: dict[str, Any]) -> None:
    rows = [(d["dimensions"]["clientRequestPath"], d["count"]) for d in data["topPaths"]]
    total = sum(v for _, v in rows)
    heading("Top Paths")
    print_table(rows, total)
    print()


def print_countries(data: dict[str, Any]) -> None:
    rows = [(d["dimensions"]["clientCountryName"], d["count"]) for d in data["countries"]]
    total = sum(v for _, v in rows)
    heading("Countries")
    print_table(rows, total)
    print()


def print_dns(data: dict[str, Any]) -> None:
    rows = [(f"{d['dimensions']['queryName']} ({d['dimensions']['responseCode']})", d["count"]) for d in data["dns"]]
    heading("DNS Queries")
    print_table(rows)
    print()


def print_hourly(data: dict[str, Any]) -> None:
    hourly = data["hourly"]
    if not hourly:
        return

    # Build a lookup of 5xx counts per hour
    err_by_hour: dict[str, int] = {}
    for d in data.get("hourly5xx", []):
        err_by_hour[d["dimensions"]["datetimeHour"]] = d["count"]

    heading("Hourly Traffic")
    max_count = max(d["count"] for d in hourly)
    for d in hourly:
        dt_hour = d["dimensions"]["datetimeHour"]
        hour = dt_hour[11:16]
        count = d["count"]
        bw = d["sum"]["edgeResponseBytes"]
        err = err_by_hour.get(dt_hour, 0)
        if PLAIN:
            err_str = f"\t{err}err" if err else ""
            print(f"  {hour}\t{count}\t{fmt_bytes(bw)}{err_str}")
        else:
            err_str = f"  !! {err} 5xx" if err else ""
            print(f"  {hour}  {count:>5} req  {fmt_bytes(bw):>10}  {bar(count, max_count, 30)}{err_str}")
    print()


SECTION_PRINTERS: dict[str, Any] = {
    "overview": print_overview,
    "cache": print_cache,
    "errors": print_errors,
    "504": print_504,
    "paths": print_paths,
    "countries": print_countries,
    "dns": print_dns,
    "hourly": print_hourly,
}


def main(args: Args) -> None:
    global PLAIN
    PLAIN = args.plain

    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        print("CLOUDFLARE_API_TOKEN not set. Run `make prod-env` first.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = build_query(ZONE_ID, start, end, args.top_n)
    data = gql(token, query)

    if args.json:
        print(json_mod.dumps(data, indent=2))
        return

    window = f"{args.hours}h" if args.hours < 48 else f"{args.hours // 24}d"
    if PLAIN:
        print(f"Cloudflare Analytics yapit.md last {window} ({start} to {end})")
    else:
        print(f"\n☁  Cloudflare Analytics — yapit.md — last {window}")
        print(f"   {start} → {end}")
    print()

    if args.section == "all":
        for printer in SECTION_PRINTERS.values():
            printer(data)
    else:
        SECTION_PRINTERS[args.section](data)


if __name__ == "__main__":
    main(tyro.cli(Args, description=__doc__))
