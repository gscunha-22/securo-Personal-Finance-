#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-$ROOT/backups/securo-$STAMP}"
mkdir -p "$OUT"

echo "Writing instance backup to $OUT"

libpq_url() {
  local raw="${1-}"
  raw="${raw/postgresql+asyncpg:\/\//postgresql://}"
  raw="${raw/postgresql+psycopg:\/\//postgresql://}"
  raw="${raw/ssl=require/sslmode=require}"
  printf '%s' "$raw"
}

uses_neon_pooler() {
  [[ "${1-}" == *-pooler.*.neon.tech* ]]
}

neon_direct_url() {
  local raw="${1-}"
  printf '%s' "${raw/-pooler./.}"
}

dump_postgres() {
  local url="${DATABASE_URL_DIRECT:-}"
  if [ -z "$url" ]; then
    url="${DATABASE_URL:-}"
    if uses_neon_pooler "$url"; then
      url="$(neon_direct_url "$url")"
    fi
  fi
  if [ -n "$url" ] && [[ "$url" == *neon.tech* || -n "${DATABASE_URL_DIRECT:-}" ]]; then
    echo "Dumping via libpq URL (direct/Neon)."
    pg_dump "$(libpq_url "$url")" -Fc > "$OUT/postgres.dump"
    pg_dump "$(libpq_url "$url")" --schema-only > "$OUT/schema.sql"
    return 0
  fi
  if docker compose ps db >/dev/null 2>&1; then
    docker compose exec -T db pg_dump -U postgres -d securo -Fc > "$OUT/postgres.dump"
    docker compose exec -T db pg_dump -U postgres -d securo --schema-only > "$OUT/schema.sql"
    return 0
  fi
  echo "docker compose db is not running and no DATABASE_URL_DIRECT was set." >&2
  exit 1
}

dump_postgres

VAULT_INCLUDED=false
if [ "${STORAGE_PROVIDER:-}" = "s3" ] && [ -n "${STORAGE_S3_BUCKET:-}" ]; then
  echo "Copying S3 vault objects."
  python3 "$ROOT/scripts/vault_s3.py" pull "$OUT/vault"
  VAULT_INCLUDED=true
fi

ATTACHMENTS_INCLUDED=false
if docker compose ps backend >/dev/null 2>&1; then
  if docker compose exec -T backend tar -C /app/data -czf - attachments > "$OUT/attachments.tar.gz"; then
    ATTACHMENTS_INCLUDED=true
  else
    echo "Attachment archive failed." >&2
    rm -f "$OUT/attachments.tar.gz"
    exit 1
  fi
fi

includes='["postgres.dump", "schema.sql"'
if [ "$VAULT_INCLUDED" = true ]; then
  includes+=', "vault/"'
fi
if [ "$ATTACHMENTS_INCLUDED" = true ]; then
  includes+=', "attachments.tar.gz"'
fi
includes+=']'

cat > "$OUT/manifest.json" <<EOF
{
  "created_at": "$STAMP",
  "includes": $includes,
  "notes": "Restore with scripts/restore-instance.sh. Workspace JSON zip from the UI does not contain original files. Neon dumps use DATABASE_URL_DIRECT. STORAGE_PROVIDER=s3 copies vault objects into vault/."
}
EOF

echo "Backup complete: $OUT"
