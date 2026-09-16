#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-$ROOT/backups/securo-$STAMP}"
mkdir -p "$OUT"

echo "Writing instance backup to $OUT"

if docker compose ps db >/dev/null 2>&1; then
  docker compose exec -T db pg_dump -U postgres -d securo -Fc > "$OUT/postgres.dump"
  docker compose exec -T db pg_dump -U postgres -d securo --schema-only > "$OUT/schema.sql"
else
  echo "docker compose db is not running; expected a custom DATABASE_URL dump." >&2
  exit 1
fi

if docker compose ps backend >/dev/null 2>&1; then
  docker compose exec -T backend tar -C /app/data -czf - attachments > "$OUT/attachments.tar.gz" || true
fi

cat > "$OUT/manifest.json" <<EOF
{
  "created_at": "$STAMP",
  "includes": ["postgres.dump", "schema.sql", "attachments.tar.gz"],
  "notes": "Restore with scripts/restore-instance.sh. Workspace JSON zip from the UI does not contain original files."
}
EOF

echo "Backup complete: $OUT"
