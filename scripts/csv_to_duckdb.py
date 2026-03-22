"""Convert exported CSV metrics to DuckDB."""

import duckdb

conn = duckdb.connect("data/metrics.duckdb")
conn.execute("DROP TABLE IF EXISTS metrics_event")
conn.execute("DROP TABLE IF EXISTS metrics_hourly")
conn.execute("DROP TABLE IF EXISTS metrics_daily")
conn.execute(
    """CREATE TABLE metrics_event AS SELECT * FROM read_csv('data/metrics_raw.csv', auto_detect=true, quote='"')"""
)
conn.execute("""CREATE TABLE metrics_hourly AS SELECT * FROM read_csv('data/metrics_hourly.csv', auto_detect=true)""")
conn.execute("""CREATE TABLE metrics_daily AS SELECT * FROM read_csv('data/metrics_daily.csv', auto_detect=true)""")
count = conn.execute("SELECT COUNT(*) FROM metrics_event").fetchone()[0]
print(f"Synced: {count} raw events")
conn.close()
