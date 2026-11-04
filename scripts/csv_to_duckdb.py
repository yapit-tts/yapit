"""Convert exported CSV metrics to DuckDB.

The file is written fresh in DuckDB's v1.0.0 storage format, which every DuckDB
since can read: the report agent queries it with the host's duckdb CLI, whose
version moves independently of the Python package that writes it.
"""

import os

import duckdb

DB = "data/metrics.duckdb"
TMP = f"{DB}.tmp"

if os.path.exists(TMP):
    os.remove(TMP)
conn = duckdb.connect(TMP, config={"storage_compatibility_version": "v1.0.0"})
conn.execute(
    """CREATE TABLE metrics_event AS SELECT * FROM read_csv('data/metrics_raw.csv', auto_detect=true, quote='"')"""
)
conn.execute("""CREATE TABLE metrics_hourly AS SELECT * FROM read_csv('data/metrics_hourly.csv', auto_detect=true)""")
conn.execute("""CREATE TABLE metrics_daily AS SELECT * FROM read_csv('data/metrics_daily.csv', auto_detect=true)""")
count = conn.execute("SELECT COUNT(*) FROM metrics_event").fetchone()[0]
conn.close()
os.replace(TMP, DB)
print(f"Synced: {count} raw events")
