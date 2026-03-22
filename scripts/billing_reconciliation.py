# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "duckdb", "pytz"]
# ///
"""Billing reconciliation — compares synthesis events vs billing events.

Runs against the local DuckDB metrics export. Pre-computes the reconciliation
so the report agent can interpret results instead of writing queries.

Two checks:
1. Event count: count(synthesis_complete) vs sum(billing_processed.events_count)
   Should be 0 for completed days. Non-zero on current day is OK (in-flight).
2. Character totals: sum(synthesis_complete.text_length) vs sum(billing_processed.text_length)
   Ratio depends on model mix (kokoro/inworld-1.5 = 1x, inworld-1.5-max = 2x).

Examples::

    uv run scripts/billing_reconciliation.py
    uv run scripts/billing_reconciliation.py --days 14
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import tyro

METRICS_DB = Path("data/metrics.duckdb")


@dataclass
class Args:
    """Billing reconciliation report."""

    days: int = 7
    """Number of days to report (most recent N days with data)."""


def main(args: Args) -> None:
    if not METRICS_DB.exists():
        print("No metrics DB found. Run `make sync-metrics` first.", file=sys.stderr)
        sys.exit(1)

    con = duckdb.connect(str(METRICS_DB), read_only=True)

    rows = con.sql(f"""
        WITH synth AS (
            SELECT
                CAST(timestamp AS DATE) AS day,
                COUNT(*) AS synth_events,
                SUM(CAST(text_length AS BIGINT)) AS synth_chars
            FROM metrics_event
            WHERE event_type = 'synthesis_complete'
              AND text_length IS NOT NULL
            GROUP BY 1
        ),
        billed AS (
            SELECT
                CAST(timestamp AS DATE) AS day,
                SUM(CAST(data->>'events_count' AS BIGINT)) AS billed_events,
                SUM(CAST(text_length AS BIGINT)) AS billed_chars
            FROM metrics_event
            WHERE event_type = 'billing_processed'
              AND data IS NOT NULL
              AND text_length IS NOT NULL
            GROUP BY 1
        )
        SELECT
            COALESCE(s.day, b.day) AS day,
            COALESCE(s.synth_events, 0) AS synth_events,
            COALESCE(b.billed_events, 0) AS billed_events,
            COALESCE(s.synth_events, 0) - COALESCE(b.billed_events, 0) AS event_delta,
            COALESCE(s.synth_chars, 0) AS synth_chars,
            COALESCE(b.billed_chars, 0) AS billed_chars
        FROM synth s
        FULL OUTER JOIN billed b ON s.day = b.day
        ORDER BY day DESC
        LIMIT {args.days}
    """).fetchall()

    if not rows:
        print("No data found.")
        return

    liveness = con.sql("""
        SELECT
            (SELECT MAX(timestamp) FROM metrics_event
             WHERE event_type = 'synthesis_complete') AS last_synth,
            (SELECT MAX(timestamp) FROM metrics_event
             WHERE event_type = 'billing_processed') AS last_billed
    """).fetchone()

    print("## Billing Reconciliation")
    print()

    if liveness:
        last_synth, last_billed = liveness
        if last_synth and last_billed:
            gap = last_synth - last_billed
            gap_minutes = int(gap.total_seconds() / 60)
            status = "OK" if gap_minutes < 60 else f"WARNING — {gap_minutes}min gap"
            print(f"Consumer liveness: last synth {last_synth:%H:%M}, last billed {last_billed:%H:%M} ({status})")
        elif last_synth and not last_billed:
            print("Consumer liveness: WARNING — synthesis events exist but NO billing events")
        print()

    today = date.today()

    print(f"{'Day':<12} {'Synth':>7} {'Billed':>7} {'Delta':>7} {'SynthChars':>11} {'BilledChars':>12}")
    print("-" * 62)

    flagged_days = []
    for day, synth_ev, billed_ev, delta, synth_ch, billed_ch in rows:
        is_today = day == today
        flag = " (today)" if is_today and delta != 0 else " !" if delta != 0 else ""
        print(f"{day!s:<12} {synth_ev:>7} {billed_ev:>7} {delta:>+7}{flag} {synth_ch:>11,} {billed_ch:>12,}")
        if delta != 0 and not is_today:
            flagged_days.append((day, delta))

    print()

    total_synth = sum(r[1] for r in rows)
    total_billed = sum(r[2] for r in rows)
    total_delta = total_synth - total_billed

    print(f"Totals ({args.days}d): {total_synth} synthesized, {total_billed} billed, delta {total_delta:+d}")

    if flagged_days:
        print()
        print("ALERT — non-zero delta on completed days:")
        for day, delta in flagged_days:
            print(f"  {day}: {delta:+d} events")

    con.close()


if __name__ == "__main__":
    main(tyro.cli(Args))
