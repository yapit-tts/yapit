#!/usr/bin/env bash
# Disk usage report for Yapit production server
# Run locally: ./scripts/disk-usage.sh
# Requires: SSH access to VPS_HOST (from .env or environment)

set -euo pipefail

# Load VPS_HOST from .env if not set
if [[ -z "${VPS_HOST:-}" ]]; then
    if [[ -f .env ]]; then
        VPS_HOST=$(grep -E '^VPS_HOST=' .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    fi
fi

if [[ -z "${VPS_HOST:-}" ]]; then
    echo "Error: VPS_HOST not set."
    echo "Usage: VPS_HOST=root@your-server ./scripts/disk-usage.sh"
    echo "   or: Add VPS_HOST=root@your-server to .env"
    exit 1
fi

echo "=== Yapit Disk Usage Report ($(date -Iseconds)) ==="
echo "Host: $VPS_HOST"
echo

ssh "$VPS_HOST" bash -s << 'REMOTE_SCRIPT'
set -euo pipefail

echo "=== Overall Disk Usage ==="
df -h / | tail -1 | awk '{print "Total: "$2"  Used: "$3" ("$5")  Available: "$4}'
echo

echo "=== Docker System ==="
docker system df 2>/dev/null || echo "(docker not available)"
echo

echo "=== Named Volumes (sorted by size) ==="
echo "SIZE     VOLUME"
for vol in $(docker volume ls -q 2>/dev/null | grep -E '^yapit_' || true); do
    mountpoint=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null)
    if [[ -d "$mountpoint" ]]; then
        size=$(du -sh "$mountpoint" 2>/dev/null | cut -f1)
        printf "%-8s %s\n" "$size" "$vol"
    fi
done | sort -hr
echo

echo "=== Cache Breakdown ==="
for cache in audio_cache document_cache extraction_cache; do
    vol="yapit_${cache}"
    mountpoint=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null || echo "")
    if [[ -n "$mountpoint" && -d "$mountpoint" ]]; then
        db_file="$mountpoint/cache.db"
        if [[ -f "$db_file" ]]; then
            db_size=$(du -h "$db_file" 2>/dev/null | cut -f1)
            wal_size=$(du -h "${db_file}-wal" 2>/dev/null | cut -f1 || echo "0")
            # Get entry count from SQLite
            count=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM cache;" 2>/dev/null || echo "?")
            printf "%-20s DB: %-6s  WAL: %-6s  Entries: %s\n" "$cache:" "$db_size" "$wal_size" "$count"
        else
            echo "$cache: (no cache.db found)"
        fi
    fi
done
echo

echo "=== Database Sizes ==="
# Main postgres
docker exec yapit-postgres-1 psql -U yapit_prod -d yapit_prod -t -c \
    "SELECT pg_size_pretty(pg_database_size('yapit_prod'));" 2>/dev/null | xargs echo "Main DB (yapit_prod):" || echo "Main DB: (unavailable)"

# Metrics timescaledb
docker exec yapit-metrics-db-1 psql -U metrics -d metrics -t -c \
    "SELECT pg_size_pretty(pg_database_size('metrics'));" 2>/dev/null | xargs echo "Metrics DB:" || echo "Metrics DB: (unavailable)"
echo

echo "=== Log Files ==="
log_vol=$(docker volume inspect yapit_gateway-data --format '{{.Mountpoint}}' 2>/dev/null || echo "")
if [[ -n "$log_vol" && -d "$log_vol/logs" ]]; then
    total=$(du -sh "$log_vol/logs" 2>/dev/null | cut -f1)
    compressed=$(find "$log_vol/logs" -name "*.gz" 2>/dev/null | wc -l)
    current=$(du -h "$log_vol/logs/gateway.jsonl" 2>/dev/null | cut -f1 || echo "0")
    echo "Total: $total  Current log: $current  Compressed files: $compressed"
else
    echo "(log directory not found)"
fi
echo

echo "=== Container Images ==="
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" 2>/dev/null | grep -E '(yapit|REPOSITORY)' | head -10
echo

echo "=== Largest Files in Volumes (top 10) ==="
for vol in $(docker volume ls -q 2>/dev/null | grep -E '^yapit_' || true); do
    mountpoint=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null)
    if [[ -d "$mountpoint" ]]; then
        find "$mountpoint" -type f -printf "%s %p\n" 2>/dev/null
    fi
done | sort -rn | head -10 | while read size path; do
    human=$(numfmt --to=iec-i --suffix=B "$size" 2>/dev/null || echo "${size}B")
    printf "%-10s %s\n" "$human" "$(basename "$path")"
done

# Append summary line to history file (append-only, never truncated)
HISTORY_FILE="/var/log/yapit-disk-history.log"

# Gather values for history line
disk_pct=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
disk_used=$(df -h / | tail -1 | awk '{print $3}')
disk_total=$(df -h / | tail -1 | awk '{print $2}')

audio_cache_size="?"
doc_cache_size="?"
extract_cache_size="?"
log_size="?"

for cache in audio_cache document_cache extraction_cache; do
    vol="yapit_${cache}"
    mountpoint=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null || echo "")
    if [[ -n "$mountpoint" ]]; then
        db_file="$mountpoint/cache.db"
        if [[ -f "$db_file" ]]; then
            size=$(du -h "$db_file" 2>/dev/null | cut -f1)
            case "$cache" in
                audio_cache) audio_cache_size="$size" ;;
                document_cache) doc_cache_size="$size" ;;
                extraction_cache) extract_cache_size="$size" ;;
            esac
        fi
    fi
done

log_vol=$(docker volume inspect yapit_gateway-data --format '{{.Mountpoint}}' 2>/dev/null || echo "")
if [[ -n "$log_vol" && -d "$log_vol/logs" ]]; then
    log_size=$(du -sh "$log_vol/logs" 2>/dev/null | cut -f1)
fi

# Write history line
echo "$(date -Iseconds) total=$disk_total used=$disk_used pct=$disk_pct audio=$audio_cache_size doc=$doc_cache_size extract=$extract_cache_size logs=$log_size" >> "$HISTORY_FILE"

REMOTE_SCRIPT

echo
echo "=== Done ==="
