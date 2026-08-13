#!/usr/bin/env bash
#
# Bazaning zaxira nusxasi.
#
# Nega kerak: migratsiya har deployda avtomatik bajariladi (docker-entrypoint.sh),
# ya'ni bitta xato migratsiya butun bazani qaytarib bo'lmaydigan holga soladi.
# Supabase'ning o'z avtomatik zaxirasi bor, lekin u boshqa birovning sozlamasi —
# bu skript bizning nazoratimizdagi nusxa.
#
# Ishlatish:
#   ./scripts/backup.sh                    # ./backups/ ichiga
#   BACKUP_DIR=/mnt/vol ./scripts/backup.sh
#   S3_BUCKET=... ./scripts/backup.sh      # olingach S3 ga yuklaydi
#
# Kunlik cron (server vaqti bo'yicha 03:00):
#   0 3 * * * cd /app && ./scripts/backup.sh >> /var/log/sotuvchi-backup.log 2>&1
#
# MUHIM: tiklashni sinab ko'rmagan zaxira — zaxira emas. Oyiga bir marta
# scripts/restore-test.sh ni ishga tushiring.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="${BACKUP_DIR}/sotuvchi-${STAMP}.sql.gz"

if [[ -z "${DATABASE_URL:-}" ]]; then
    if [[ -f .env ]]; then
        # .env dan faqat kerakli qatorni olamiz — butun faylni source qilish
        # tasodifiy o'zgaruvchilarni ham muhitga chiqarib yuboradi.
        DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
    fi
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "XATO: DATABASE_URL topilmadi." >&2
    exit 1
fi

# pg_dump SQLAlchemy'ning +asyncpg qo'shimchasini tushunmaydi.
PG_URL="${DATABASE_URL/+asyncpg/}"

command -v pg_dump >/dev/null || { echo "XATO: pg_dump o'rnatilmagan." >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
echo "[$(date -u +%H:%M:%S)] Zaxira olinmoqda -> ${FILE}"

# --no-owner / --no-acl: nusxa boshqa foydalanuvchi ostida ham tiklanadi.
pg_dump --no-owner --no-acl --format=plain "$PG_URL" | gzip -9 > "$FILE"

SIZE="$(du -h "$FILE" | cut -f1)"

# Bo'sh yoki juda kichik fayl — muvaffaqiyat emas. Jim o'tib ketsa, tiklash
# kunida bilib qolamiz.
MIN_BYTES=10240
ACTUAL=$(wc -c < "$FILE")
if (( ACTUAL < MIN_BYTES )); then
    echo "XATO: zaxira juda kichik (${ACTUAL} bayt) — nimadir noto'g'ri." >&2
    exit 1
fi

# Arxiv butunligini tekshiramiz: buzilgan gzip ham fayl bo'lib turaveradi.
gzip -t "$FILE"
echo "[$(date -u +%H:%M:%S)] Tayyor: ${SIZE}"

if [[ -n "${S3_BUCKET:-}" ]] && command -v aws >/dev/null; then
    ENDPOINT_ARG=""
    [[ -n "${S3_ENDPOINT_URL:-}" ]] && ENDPOINT_ARG="--endpoint-url ${S3_ENDPOINT_URL}"
    # shellcheck disable=SC2086
    aws s3 cp "$FILE" "s3://${S3_BUCKET}/backups/" $ENDPOINT_ARG
    echo "[$(date -u +%H:%M:%S)] S3 ga yuklandi: s3://${S3_BUCKET}/backups/"
fi

find "$BACKUP_DIR" -name 'sotuvchi-*.sql.gz' -mtime "+${KEEP_DAYS}" -delete
echo "[$(date -u +%H:%M:%S)] ${KEEP_DAYS} kundan eski nusxalar tozalandi."
