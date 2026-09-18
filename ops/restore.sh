#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: RESTORE_CONFIRM=<database> $0 /backups/northstar-YYYYMMDDTHHMMSSZ.dump" >&2
  exit 2
fi

backup_file="$1"
: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"

if [ "${RESTORE_CONFIRM:-}" != "$PGDATABASE" ]; then
  echo "Set RESTORE_CONFIRM=$PGDATABASE to confirm replacing that database." >&2
  exit 2
fi
if [ ! -f "$backup_file" ]; then
  echo "Backup file not found: $backup_file" >&2
  exit 2
fi

pg_restore --list "$backup_file" >/dev/null
pg_restore \
  --clean \
  --if-exists \
  --exit-on-error \
  --no-owner \
  --no-acl \
  --dbname="$PGDATABASE" \
  "$backup_file"
echo "Restore completed and archive structure verified."
