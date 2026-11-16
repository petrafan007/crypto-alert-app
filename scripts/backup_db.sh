#!/usr/bin/env bash
# Nightly PostgreSQL backup for Crypto & Securities Dashboard.
#
# * Daily: everything except bulk research capture payloads (kept 14 days).
# * Sunday: a full dump including research data (kept 2 weeks).
# The database also holds the credential encryption key, so backups are
# written owner-only (umask 077) into a private directory.
set -euo pipefail
umask 077

DB_NAME="${DB_NAME:-cryptoalertapp}"
DB_HOST="${DB_HOST:-/var/run/postgresql}"
DB_PORT="${DB_PORT:-5433}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/crypto-dashboard}"
DAILY_KEEP_DAYS="${DAILY_KEEP_DAYS:-14}"
FULL_KEEP_COUNT="${FULL_KEEP_COUNT:-2}"
OFFSITE_DIR="${OFFSITE_DIR:-}"   # optional: a mounted NAS/cloud folder for a second copy

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"

if [ "$(date +%u)" = "7" ] || [ "${FULL:-0}" = "1" ]; then
    target="$BACKUP_DIR/full-$stamp.dump"
    pg_dump -h "$DB_HOST" -p "$DB_PORT" -Fc -Z 6 -f "$target.partial" "$DB_NAME"
else
    target="$BACKUP_DIR/daily-$stamp.dump"
    pg_dump -h "$DB_HOST" -p "$DB_PORT" -Fc -Z 6 \
        --exclude-table-data=research_captures --exclude-table-data=research_datasets \
        -f "$target.partial" "$DB_NAME"
fi
# A dump that cannot be listed is not a backup.
pg_restore --list "$target.partial" >/dev/null
mv "$target.partial" "$target"

find "$BACKUP_DIR" -name 'daily-*.dump' -mtime +"$DAILY_KEEP_DAYS" -delete
ls -1t "$BACKUP_DIR"/full-*.dump 2>/dev/null | tail -n +"$((FULL_KEEP_COUNT + 1))" | xargs -r rm -f
find "$BACKUP_DIR" -name '*.partial' -mmin +720 -delete

if [ -n "$OFFSITE_DIR" ] && [ -d "$OFFSITE_DIR" ]; then
    cp "$target" "$OFFSITE_DIR/"
fi
echo "Backup written: $target ($(du -h "$target" | cut -f1))"
