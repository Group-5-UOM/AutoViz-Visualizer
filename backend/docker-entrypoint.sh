#!/bin/sh
# Container entrypoint: bring the schema up to date, then start the server.
#
# Alembic reads DATABASE_URL via autoviz.core.config.settings (alembic/env.py),
# so no connection string is duplicated here. Migrations are idempotent —
# `upgrade head` is a no-op when the DB is already current.
set -e

echo "[entrypoint] applying database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
