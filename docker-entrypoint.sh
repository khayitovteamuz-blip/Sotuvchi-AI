#!/bin/sh
# Bring the schema up to date, then hand over to the server.
#
# Without this a deploy ships new code against an old schema, and the first
# request that touches a new column fails in production rather than here.
#
# Alembic runs inside a transaction on Postgres, so if two instances start at
# once one applies the migration and the other finds the version already set.
# Set RUN_MIGRATIONS=false to take this over manually (e.g. a release phase).
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "▶ Migratsiyalar qo'llanmoqda..."
    alembic upgrade head
    echo "✔ Sxema yangilandi"
fi

exec "$@"
