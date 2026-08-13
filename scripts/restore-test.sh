#!/usr/bin/env bash
#
# Tiklash mashqi — zaxira haqiqatan ishlaydimi?
#
# Sinab ko'rilmagan zaxira zaxira emas. Bu skript oxirgi nusxani ALOHIDA
# vaqtinchalik bazaga tiklaydi, jadvallar va qatorlar sonini sanaydi va
# bazani o'chiradi. Ishlaydigan bazaga TEGMAYDI.
#
# Ishlatish:  ./scripts/restore-test.sh [zaxira-fayli.sql.gz]
# Oyiga bir marta bajarilsin.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
FILE="${1:-}"

if [[ -z "$FILE" ]]; then
    FILE="$(ls -t "${BACKUP_DIR}"/sotuvchi-*.sql.gz 2>/dev/null | head -1 || true)"
fi
[[ -n "$FILE" && -f "$FILE" ]] || { echo "XATO: zaxira fayli topilmadi." >&2; exit 1; }

if [[ -z "${DATABASE_URL:-}" && -f .env ]]; then
    DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
fi
[[ -n "${DATABASE_URL:-}" ]] || { echo "XATO: DATABASE_URL topilmadi." >&2; exit 1; }

PG_URL="${DATABASE_URL/+asyncpg/}"
BASE_URL="${PG_URL%/*}"
TEST_DB="sotuvchi_restore_test_$(date -u +%s)"

echo "Fayl : ${FILE}"
echo "Baza : ${TEST_DB} (vaqtinchalik)"

cleanup() {
    psql "${BASE_URL}/postgres" -q -c "DROP DATABASE IF EXISTS ${TEST_DB};" >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql "${BASE_URL}/postgres" -q -c "CREATE DATABASE ${TEST_DB};"

# pgvector kabi kengaytmalar dump ichida CREATE EXTENSION bilan keladi,
# lekin ular oldindan mavjud bo'lishi kerak bo'lgan holatlar ham bor.
psql "${BASE_URL}/${TEST_DB}" -q -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
psql "${BASE_URL}/${TEST_DB}" -q -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null || true

echo "Tiklanmoqda…"
gunzip -c "$FILE" | psql "${BASE_URL}/${TEST_DB}" -q -v ON_ERROR_STOP=0 > /dev/null

echo
echo "Tiklangan ma'lumot:"
psql "${BASE_URL}/${TEST_DB}" -t -A -F' | ' -c "
  SELECT 'tenants', count(*) FROM tenants
  UNION ALL SELECT 'users', count(*) FROM users
  UNION ALL SELECT 'products', count(*) FROM products
  UNION ALL SELECT 'orders', count(*) FROM orders
  UNION ALL SELECT 'customers', count(*) FROM customers
  UNION ALL SELECT 'messages', count(*) FROM messages
  UNION ALL SELECT 'payments', count(*) FROM payments;"

TENANTS=$(psql "${BASE_URL}/${TEST_DB}" -t -A -c "SELECT count(*) FROM tenants;")
echo
if [[ "$TENANTS" -gt 0 ]]; then
    echo "✅ Zaxira ishlaydi — ${TENANTS} ta biznes tiklandi."
else
    echo "❌ Zaxirada biznes yo'q. Bu nusxaga ishonib bo'lmaydi." >&2
    exit 1
fi
