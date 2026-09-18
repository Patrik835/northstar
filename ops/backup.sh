#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
: "${BACKUP_RETENTION_DAYS:=14}"

mkdir -p /backups

backup_once() {
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  temporary="/backups/.northstar-${timestamp}.dump.tmp"
  destination="/backups/northstar-${timestamp}.dump"
  if ! pg_dump --format=custom --no-owner --no-acl --file="$temporary" "$PGDATABASE"; then
    rm -f "$temporary"
    return 1
  fi
  if ! pg_restore --list "$temporary" >/dev/null; then
    rm -f "$temporary"
    return 1
  fi
  mv "$temporary" "$destination"
  date -u +%Y-%m-%dT%H:%M:%SZ > /backups/.latest-success.tmp
  mv /backups/.latest-success.tmp /backups/latest-success
  if ! find /backups -type f -name 'northstar-*.dump' -mtime "+${BACKUP_RETENTION_DAYS}" -delete; then
    echo "Backup succeeded, but retention cleanup failed" >&2
  fi
  echo "Verified PostgreSQL backup created: ${destination}"
}

if [ "${1:-}" = "once" ]; then
  backup_once
  exit 0
fi

while true; do
  if ! backup_once; then
    echo "PostgreSQL backup failed" >&2
  fi
  sleep "$BACKUP_INTERVAL_SECONDS"
done
