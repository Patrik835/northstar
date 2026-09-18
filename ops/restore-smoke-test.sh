#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /backups/northstar-YYYYMMDDTHHMMSSZ.dump" >&2
  exit 2
fi

backup_file="$1"
: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
test_database="northstar_restore_test"

pg_restore --list "$backup_file" >/dev/null
dropdb --if-exists "$test_database"
createdb "$test_database"
cleanup() { dropdb --if-exists "$test_database"; }
trap cleanup EXIT INT TERM
pg_restore --exit-on-error --no-owner --no-acl --dbname="$test_database" "$backup_file"
psql --dbname="$test_database" --tuples-only --command="SELECT version_num FROM alembic_version;"
echo "Restore smoke test passed."
