#!/bin/sh
# Persistent API boot: migrate on the direct Neon URL, then serve.
# Bind PORT when a PaaS injects it (Render/Fly). Default 8000 matches Compose/Helm.
set -e
alembic upgrade head
# Behind Vercel rewrite / Render / nginx, honor X-Forwarded-* so HTTPS
# scheme and client IP match TRUSTED_PROXY_HOPS (Render Blueprint sets 1).
if [ "${TRUSTED_PROXY_HOPS:-0}" != "0" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
    --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
