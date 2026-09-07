"""Metrics pipeline freshness: is the newest metrics event recent enough for a live writer?

Run by report.sh after sync-data. The gateway's metrics writer writes a `heartbeat`
event whenever an hour passes without any other write, so a live pipeline never
leaves a longer gap in metrics_event; a newest event older than STALE_AFTER_H means
the writer is dead, wedged, or cut off from its DB. The newest gateway log line is
printed alongside, to tell a silent metrics writer from a silent gateway.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from yapit.gateway.metrics import HEARTBEAT_INTERVAL_S

DB_PATH = Path("data/metrics.duckdb")
LOG_PATH = Path("data/logs/gateway.jsonl")
HEARTBEAT_H = HEARTBEAT_INTERVAL_S / 3600
STALE_AFTER_H = 2 * HEARTBEAT_H  # one missed heartbeat is jitter, two is an outage


def main() -> None:
    now = datetime.now(UTC)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    last_event = con.execute("SELECT max(timestamp) FROM metrics_event").fetchone()[0]  # ty: ignore[possibly-unbound-implicit-call]
    assert last_event is not None, "metrics_event table is empty"
    event_age_h = (now - last_event).total_seconds() / 3600
    print(f"Last metrics event:  {last_event:%Y-%m-%d %H:%M:%S %Z} ({event_age_h:.1f}h ago)")

    last_log = _last_log_time()
    log_age_h = (now - last_log).total_seconds() / 3600 if last_log else None
    if log_age_h is not None:
        print(f"Last gateway log:    {last_log:%Y-%m-%d %H:%M:%S %Z} ({log_age_h:.1f}h ago)")

    if event_age_h <= STALE_AFTER_H:
        print(f"✅ FRESH — metrics pipeline is live (a live writer never goes quiet for more than {HEARTBEAT_H:.0f}h).")
        return
    if log_age_h is not None and log_age_h > STALE_AFTER_H:
        print(
            f"🚨 STALE — no metrics event for {event_age_h:.1f}h and no gateway log line for {log_age_h:.1f}h: "
            "the gateway itself has gone silent, not just its metrics writer (P0). Lead the report with this."
        )
        return
    gateway_alive = f" while the gateway logged {log_age_h:.1f}h ago" if log_age_h is not None else ""
    print(
        f"🚨 STALE — no metrics event for {event_age_h:.1f}h{gateway_alive}, though a live writer "
        f"heartbeats every {HEARTBEAT_H:.0f}h. The metrics pipeline is DOWN (P0). Lead the report with this; "
        "all metrics-based sections only cover the period before the gap."
    )


def _last_log_time() -> datetime | None:
    """Timestamp of the last line in the current gateway log (reads only the file tail)."""
    if not LOG_PATH.exists():
        return None
    with LOG_PATH.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 65536))
        lines = f.read().splitlines()
    for raw in reversed(lines):
        try:
            ts = json.loads(raw)["record"]["time"]["timestamp"]
            return datetime.fromtimestamp(ts, tz=UTC)
        except (json.JSONDecodeError, KeyError):
            continue  # partial first line from the seek, or malformed entry
    return None


if __name__ == "__main__":
    main()
