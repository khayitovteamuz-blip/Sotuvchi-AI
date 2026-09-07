#!/bin/sh
# Bring the schema up to date, then hand over to the server.
#
# Without this a deploy ships new code against an old schema, and the first
# request that touches a new column fails in production rather than here.
#
# alembic/env.py takes a PostgreSQL advisory lock, so rolling deploys serialize
# migration writers instead of racing on the same schema revision.
# Set RUN_MIGRATIONS=false to take this over manually (e.g. a release phase).
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "▶ Migratsiyalar qo'llanmoqda..."
    alembic upgrade head
    echo "✔ Sxema yangilandi"
fi

exec "$@"
