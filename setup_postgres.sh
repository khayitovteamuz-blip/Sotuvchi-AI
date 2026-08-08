#!/usr/bin/env bash
#
# Sotuvchi AI — Postgres + pgvector setup (macOS / Homebrew)
# Homebrew allaqachon o'rnatilgan bo'lishi kerak (u parol so'raydi, alohida qadamda).
# Bu skript sudo TALAB QILMAYDI.
#
set -euo pipefail

echo "──────────────────────────────────────────────"
echo " Sotuvchi AI — Postgres o'rnatish va sozlash"
echo "──────────────────────────────────────────────"

# 1) Homebrew bormi?
if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Homebrew topilmadi."
  echo "   Avval shuni ishga tushiring (u parol so'raydi):"
  echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "   So'ng bu skriptni qayta ishga tushiring."
  exit 1
fi

BREW_PREFIX="$(brew --prefix)"
echo "✅ Homebrew: $BREW_PREFIX"

# 2) postgresql@16 + pgvector o'rnatish
echo "→ postgresql@16 va pgvector o'rnatilyapti (bir necha daqiqa)..."
brew install postgresql@16 pgvector

# 3) postgresql@16 keg-only — PATH ga qo'shamiz (shu sessiya uchun)
export PATH="$BREW_PREFIX/opt/postgresql@16/bin:$PATH"

# 4) Serverni ishga tushirish
echo "→ Postgres server ishga tushirilyapti..."
brew services start postgresql@16 || true

# 5) Server tayyor bo'lguncha kutamiz
echo "→ Server tayyor bo'lishini kutyapmiz..."
for i in $(seq 1 30); do
  if pg_isready -q 2>/dev/null; then break; fi
  sleep 1
done

if ! pg_isready -q 2>/dev/null; then
  echo "❌ Postgres server ishga tushmadi. 'brew services list' bilan tekshiring."
  exit 1
fi
echo "✅ Postgres ishlayapti."

# 6) Ma'lumotlar bazasini yaratish
DB_NAME="sotuvchi_ai"
if psql -lqt 2>/dev/null | cut -d '|' -f 1 | grep -qw "$DB_NAME"; then
  echo "ℹ️  '$DB_NAME' bazasi allaqachon mavjud."
else
  createdb "$DB_NAME"
  echo "✅ '$DB_NAME' bazasi yaratildi."
fi

# 7) pgvector kengaytmasini yoqish
psql "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
echo "✅ pgvector kengaytmasi yoqildi."

# 8) Tekshirish + connection URL
PG_USER="$(whoami)"
echo ""
echo "──────────────────────────────────────────────"
echo " ✅ TAYYOR"
echo "──────────────────────────────────────────────"
psql "$DB_NAME" -c "SELECT version();" | head -3
echo ""
echo " .env fayliga qo'shiladigan qator (men qo'shaman):"
echo "   DATABASE_URL=postgresql+asyncpg://$PG_USER@localhost:5432/$DB_NAME"
echo ""
echo " PATH ga doimiy qo'shish uchun (ixtiyoriy):"
echo "   echo 'export PATH=\"$BREW_PREFIX/opt/postgresql@16/bin:\$PATH\"' >> ~/.zshrc"
echo "──────────────────────────────────────────────"
