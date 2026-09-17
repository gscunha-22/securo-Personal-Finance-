#!/bin/sh
# Persistent worker/beat boot: migrate on the direct Neon URL, then run Celery.
# Render and Compose may start these before the API finishes alembic.
set -e
alembic upgrade head
exec celery -A app.worker "$@"
