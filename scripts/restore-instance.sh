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

libpq_url() {
  local raw="${1-}"
  raw="${raw/postgresql+asyncpg:\/\//postgresql://}"
  raw="${raw/postgresql+psycopg:\/\//postgresql://}"
  raw="${raw/ssl=require/sslmode=require}"
  printf '%s' "$raw"
}

restore_postgres() {
  local url="${DATABASE_URL_DIRECT:-}"
  if [ -z "$url" ]; then
    url="${DATABASE_URL:-}"
  fi
  if [ -n "$url" ] && [[ "$url" == *neon.tech* || -n "${DATABASE_URL_DIRECT:-}" ]]; then
    pg_restore --clean --if-exists --no-owner -d "$(libpq_url "$url")" "$SRC/postgres.dump"
    return 0
  fi
  docker compose exec -T db pg_restore --clean --if-exists -U postgres -d securo < "$SRC/postgres.dump"
}

restore_postgres

if [ -d "$SRC/vault" ]; then
  echo "Restoring S3 vault objects."
  python3 "$(cd "$(dirname "$0")" && pwd)/vault_s3.py" push "$SRC/vault"
fi

if [ -f "$SRC/attachments.tar.gz" ]; then
  SAFE="$(mktemp)"
  python3 - "$SRC/attachments.tar.gz" "$SAFE" <<'PY'
import sys
import tarfile
import io

src, dest = sys.argv[1], sys.argv[2]
out = io.BytesIO()
with tarfile.open(src, "r:*") as incoming, tarfile.open(fileobj=out, mode="w:gz") as outgoing:
    for member in incoming.getmembers():
        name = member.name.replace("\\", "/")
        if member.issym() or member.islnk():
            raise SystemExit(f"Refusing symlink in archive: {name}")
        if name.startswith("/") or ".." in name.split("/"):
            raise SystemExit(f"Refusing path traversal in archive: {name}")
        if not member.isfile():
            continue
        extracted = incoming.extractfile(member)
        if extracted is None:
            continue
        data = extracted.read()
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        outgoing.addfile(info, io.BytesIO(data))
with open(dest, "wb") as fh:
    fh.write(out.getvalue())
PY
  docker compose exec -T backend tar -C /app/data -xzf - < "$SAFE"
  rm -f "$SAFE"
fi

echo "Restore complete. Restart the API/worker if they were running during restore."
