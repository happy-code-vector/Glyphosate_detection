#!/usr/bin/env sh
# Cloud Run container entrypoint.
# 1. Pull a fresh read-only DB from GCS (no-op when DB_GCS_URI is unset).
# 2. Hand off to uvicorn.
#
# Cloud Run sets $PORT (default 8080). min-instances=1 keeps one warm instance,
# so this runs once per revision/cold-start, not per request.
set -e

python -m api.fetch_db

exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8080}"
