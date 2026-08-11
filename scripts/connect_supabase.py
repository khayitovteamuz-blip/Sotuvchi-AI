"""
Connect the app to a Supabase Postgres database.

Paste the connection string once; this script normalises it, tests it, checks
pgvector, and writes it to .env — so no shell quoting, no password in your
shell history, and no silent typos.

Run:  .venv/bin/python -m scripts.connect_supabase
"""
import asyncio
import getpass
import re
import sys
from urllib.parse import quote, urlsplit, urlunsplit

from app.core.config import BASE_DIR

ENV_PATH = BASE_DIR / ".env"


def normalise(raw: str) -> str:
    """Turn any Supabase-provided URI into one asyncpg understands."""
    url = raw.strip().strip('"').strip("'")

    # Supabase shows postgresql:// or postgres://; SQLAlchemy needs the driver
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)

    # A password containing @ / # / : breaks URL parsing unless percent-encoded.
    # The password is greedy up to the LAST @ — the host can't contain one, but
    # a password very well might ("MyP@ss123").
    m = re.match(r"^(postgresql\+asyncpg://)([^:/@]+):(.+)@([^@]+)$", url)
    if m:
        scheme, user, pwd, host = m.groups()
        if "%" not in pwd:                       # don't double-encode
            url = f"{scheme}{user}:{quote(pwd, safe='')}@{host}"

    # Strip query params (e.g. ?sslmode=require) — asyncpg rejects libpq-style ones
    parts = urlsplit(url)
    if parts.query:
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    return url


def masked(url: str) -> str:
    """Hide the password. Greedy to the last @, matching normalise()."""
    return re.sub(r"(//[^:/@]+:).+(@[^@]+)$", r"\1••••••\2", url)


async def verify(url: str) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    # Supabase's transaction pooler (port 6543) can't do prepared statements,
    # which asyncpg uses by default — disabling the cache keeps both ports working.
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as conn:
            ver = (await conn.execute(text("SELECT version()"))).scalar()
            print(f"\n  ✅ Ulanish muvaffaqiyatli\n     {ver.split(',')[0]}")

            has_vector = (await conn.execute(text(
                "SELECT 1 FROM pg_extension WHERE extname='vector'"
            ))).scalar()
            if has_vector:
                print("     ✅ pgvector yoqilgan")
            else:
                print("     ⚠️  pgvector yoqilmagan — yoqishga urinaman...")
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    await conn.commit()
                    print("     ✅ pgvector yoqildi")
                except Exception:
                    print("     ❌ Yoqib bo'lmadi. Supabase panelida:")
                    print("        Database → Extensions → 'vector' ni yoqing")

            tables = (await conn.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            ))).scalar()
            print(f"     Bazadagi jadvallar: {tables}")
        return True
    except Exception as e:
        print(f"\n  ❌ Ulanib bo'lmadi:\n     {str(e)[:220]}")
        print("\n  Tez-tez uchraydigan sabablar:")
        print("   • Parol noto'g'ri (Supabase → Settings → Database → Reset password)")
        print("   • Connection string 'URI' emas, boshqa formatda nusxalangan")
        print("   • Internet yoki Supabase loyihasi to'xtatilgan (paused)")
        return False
    finally:
        await engine.dispose()


def write_env(url: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").split("\n") if ENV_PATH.exists() else []
    out, replaced = [], False
    for ln in lines:
        if ln.startswith("DATABASE_URL="):
            if not replaced:
                out.append(f"DATABASE_URL={url}")
                replaced = True
            # drop any duplicates
        elif ln.startswith("#OLD_DATABASE_URL="):
            continue
        else:
            out.append(ln)
    if not replaced:
        out.append(f"DATABASE_URL={url}")
    ENV_PATH.write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    print("""
╔══════════════════════════════════════════════════════════════╗
║              Supabase bazasiga ulanish                        ║
╚══════════════════════════════════════════════════════════════╝

  Connection string ni qayerdan olasiz:

   1. supabase.com  →  loyihangizni oching
   2. Chap menyu pastida:  ⚙️  Project Settings
   3. Database  bo'limi
   4. "Connection string"  →  URI  tabini tanlang
   5. Butun qatorni nusxalang (Copy tugmasi bor)

  U shunday ko'rinadi:
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres

  ⚠️  [YOUR-PASSWORD] o'rniga haqiqiy parolingizni qo'ying.
      Parolni eslamasangiz: Settings → Database → Reset database password
""")

    raw = getpass.getpass("  Connection string (yozganingiz ko'rinmaydi, bu normal):\n  > ")
    if not raw.strip():
        print("\n  Bekor qilindi.")
        sys.exit(1)

    url = normalise(raw)
    if "supabase" not in url and "postgres" not in url:
        print("\n  ❌ Bu connection string ga o'xshamaydi. Qaytadan urinib ko'ring.")
        sys.exit(1)

    print(f"\n  Tekshirilmoqda: {masked(url)}")
    if not asyncio.run(verify(url)):
        print("\n  .env o'zgartirilmadi.")
        sys.exit(1)

    write_env(url)
    print("""
  ✅ .env ga yozildi.

  Keyingi qadam — jadvallarni yaratish va ma'lumotni ko'chirish:
     .venv/bin/alembic upgrade head
     .venv/bin/python -m scripts.migrate_to_supabase
""")


if __name__ == "__main__":
    main()
