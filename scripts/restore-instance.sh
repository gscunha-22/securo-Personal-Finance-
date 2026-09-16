#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: scripts/restore-instance.sh /path/to/backup-dir" >&2
  exit 1
fi

SRC="$1"
if [ ! -f "$SRC/postgres.dump" ]; then
  echo "Missing $SRC/postgres.dump" >&2
  exit 1
fi

echo "This replaces the running database. Confirm the instance is stopped for writes."

docker compose exec -T db pg_restore --clean --if-exists -U postgres -d securo < "$SRC/postgres.dump"

if [ -f "$SRC/attachments.tar.gz" ]; then
  docker compose exec -T backend tar -C /app/data -xzf - < "$SRC/attachments.tar.gz"
fi

echo "Restore complete. Restart the API/worker if they were running during restore."
