#!/bin/sh
# Persistent API boot: migrate on the direct Neon URL, then serve.
# Bind PORT when a PaaS injects it (Render/Fly). Default 8000 matches Compose/Helm.
set -e
alembic upgrade head
# Resume of an older Render service may omit TRUSTED_PROXY_HOPS. These
# platforms still terminate TLS in front of us, so default one hop and
# honor X-Forwarded-* (scheme + client IP) for the Vercel rewrite.
if [ -z "${TRUSTED_PROXY_HOPS:-}" ]; then
  if [ -n "${RENDER:-}" ] || [ -n "${FLY_APP_NAME:-}" ] || [ -n "${RAILWAY_ENVIRONMENT:-}" ]; then
    TRUSTED_PROXY_HOPS=1
    export TRUSTED_PROXY_HOPS
  fi
fi
if [ "${TRUSTED_PROXY_HOPS:-0}" != "0" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
    --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
