#!/bin/sh
# Periodic PostgreSQL backup for Vitals.
#
# Runs as the vitals_backup sidecar (postgres:15-alpine, which ships pg_dump).
# Dumps the database, gzips it, writes atomically (.tmp -> final) into
# /backups, then prunes dumps older than the retention window.
# One dump on start, then once every 24h.
set -eu

BACKUP_DIR="${VITALS_BACKUP_DIR:-/backups}"
RETENTION_DAYS="${VITALS_BACKUP_RETENTION_DAYS:-7}"
INTERVAL_SECONDS="${VITALS_BACKUP_INTERVAL_SECONDS:-86400}"

mkdir -p "$BACKUP_DIR"
echo "[backup] starting — dir=$BACKUP_DIR retention=${RETENTION_DAYS}d interval=${INTERVAL_SECONDS}s"

while true; do
    ts="$(date +%Y%m%d_%H%M%S)"
    out="$BACKUP_DIR/vitals_${ts}.sql.gz"
    # PGHOST/PGUSER/PGPASSWORD/PGDATABASE come from the environment (compose).
    if pg_dump --no-owner --no-privileges | gzip -c > "$out.tmp"; then
        mv "$out.tmp" "$out"
        echo "[backup] wrote $out ($(wc -c < "$out") bytes)"
    else
        echo "[backup] ERROR: pg_dump failed at $ts" >&2
        rm -f "$out.tmp"
    fi

    # Rotation: drop dumps older than the retention window.
    deleted="$(find "$BACKUP_DIR" -name 'vitals_*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -print -delete | wc -l)"
    if [ "$deleted" -gt 0 ]; then
        echo "[backup] pruned $deleted dump(s) older than ${RETENTION_DAYS}d"
    fi

    sleep "$INTERVAL_SECONDS"
done
