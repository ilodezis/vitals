#!/bin/sh
# Periodic backup for Vitals: the PostgreSQL database + the Garmin token store.
#
# Runs as the vitals_backup sidecar (postgres:15-alpine, which ships pg_dump).
# Dumps the database, verifies the dump, gzips it, writes atomically
# (.tmp -> final) into /backups, archives the Garmin session volume next to it,
# then prunes both older than the retention window. One pass on start, then once
# every 24h (VITALS_BACKUP_ONCE=1 runs a single pass and exits with its status).
#
# The Garmin archive is small but it is the one file in this project that may be
# unrecoverable: Garmin's login flow changes without notice, so a lost token can
# mean the integration simply cannot be logged back in. The database can always
# be re-synced from Garmin; the session cannot be re-derived from anything.
#
# A failed database dump is never promoted to a backup: plain /bin/sh has no
# pipefail, so `pg_dump | gzip` would report gzip's success and a dead pg_dump
# would leave an empty archive that looks like a normal one. The dump goes to an
# uncompressed temp file first, its own exit status and the trailer pg_dump writes
# only on completion are checked, and only then is it compressed and renamed.
# A failure leaves a marker in $BACKUP_DIR/status/ that the app's /health reads;
# the next good dump removes it.
#
# Each pass first waits for the database with pg_isready: after a host reboot the
# sidecar starts before Postgres accepts connections, and a refused first dump
# would keep /health red until the next pass a whole interval later. If the
# database is still not ready after the last attempt, the dump runs anyway and
# fails the normal way.
set -eu

BACKUP_DIR="${VITALS_BACKUP_DIR:-/backups}"
RETENTION_DAYS="${VITALS_BACKUP_RETENTION_DAYS:-7}"
INTERVAL_SECONDS="${VITALS_BACKUP_INTERVAL_SECONDS:-86400}"
GARMIN_SESSION_DIR="${VITALS_GARMIN_SESSION_DIR:-/garmin_session}"
ONCE="${VITALS_BACKUP_ONCE:-0}"
DB_WAIT_ATTEMPTS="${VITALS_BACKUP_DB_WAIT_ATTEMPTS:-60}"
DB_WAIT_POLL_SECONDS="${VITALS_BACKUP_DB_WAIT_POLL_SECONDS:-2}"
STATUS_DIR="$BACKUP_DIR/status"
FAILED_MARKER="$STATUS_DIR/backup_failed"
DUMP_TRAILER="PostgreSQL database dump complete"

mkdir -p "$BACKUP_DIR" "$STATUS_DIR"
echo "[backup] starting — dir=$BACKUP_DIR retention=${RETENTION_DAYS}d interval=${INTERVAL_SECONDS}s"

# Prints the newest file matching a glob pattern (names carry the timestamp, so
# the lexical maximum is the newest), or nothing when there is none.
newest() {
    ls -1 "$BACKUP_DIR"/$1 2>/dev/null | sort | tail -n 1
}

fail_dump() {
    echo "[backup] ERROR: database dump failed at $ts: $1" >&2
    rm -f "$raw" "$out.tmp"
    printf '%s %s\n' "$ts" "$1" > "$FAILED_MARKER"
    dump_ok=0
}

wait_for_db() {
    attempt=1
    until pg_isready -q; do
        if [ "$attempt" -ge "$DB_WAIT_ATTEMPTS" ]; then
            echo "[backup] WARN: database not ready after $attempt attempts — dumping anyway" >&2
            return 0
        fi
        attempt=$((attempt + 1))
        sleep "$DB_WAIT_POLL_SECONDS"
    done
}

while true; do
    wait_for_db
    ts="$(date +%Y%m%d_%H%M%S)"
    out="$BACKUP_DIR/vitals_${ts}.sql.gz"
    raw="$BACKUP_DIR/vitals_${ts}.sql.tmp"
    dump_ok=1
    # PGHOST/PGUSER/PGPASSWORD/PGDATABASE come from the environment (compose).
    if ! pg_dump --no-owner --no-privileges > "$raw"; then
        fail_dump "pg_dump exited with an error"
    elif ! tail -n 5 "$raw" | grep -q "$DUMP_TRAILER"; then
        fail_dump "dump is incomplete (no completion trailer)"
    elif ! gzip -c "$raw" > "$out.tmp"; then
        fail_dump "gzip failed"
    else
        rm -f "$raw"
        mv "$out.tmp" "$out"
        rm -f "$FAILED_MARKER"
        echo "[backup] wrote $out ($(wc -c < "$out") bytes)"
    fi

    # Garmin token store (read-only mount of the vitals_garmin_session volume).
    if [ -d "$GARMIN_SESSION_DIR" ]; then
        tokens="$BACKUP_DIR/garmin_session_${ts}.tar.gz"
        if tar -czf "$tokens.tmp" -C "$GARMIN_SESSION_DIR" .; then
            mv "$tokens.tmp" "$tokens"
            chmod 600 "$tokens"  # session tokens: owner-only, like a credential
            echo "[backup] wrote $tokens ($(wc -c < "$tokens") bytes)"
        else
            echo "[backup] ERROR: garmin session archive failed at $ts" >&2
            rm -f "$tokens.tmp"
        fi
    else
        echo "[backup] WARN: no Garmin session dir at $GARMIN_SESSION_DIR — not archived" >&2
    fi

    # Rotation: drop backups older than the retention window — but never the
    # newest one of each kind, so a failing streak longer than the window still
    # leaves the last good copy on disk.
    keep_dump="$(newest 'vitals_*.sql.gz')"
    keep_tokens="$(newest 'garmin_session_*.tar.gz')"
    deleted="$(find "$BACKUP_DIR" \( -name 'vitals_*.sql.gz' -o -name 'garmin_session_*.tar.gz' \) -type f -mtime +"$RETENTION_DAYS" \
        ! -path "${keep_dump:-/nonexistent}" ! -path "${keep_tokens:-/nonexistent}" -print -delete | wc -l)"
    if [ "$deleted" -gt 0 ]; then
        echo "[backup] pruned $deleted file(s) older than ${RETENTION_DAYS}d"
    fi

    if [ "$ONCE" = "1" ]; then
        [ "$dump_ok" = "1" ] && exit 0
        exit 1
    fi
    sleep "$INTERVAL_SECONDS"
done
