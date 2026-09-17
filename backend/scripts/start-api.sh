#!/bin/sh
# Persistent API boot: migrate on the direct Neon URL, then serve.
# Bind PORT when a PaaS injects it (Render/Fly). Default 8000 matches Compose/Helm.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
