"""
Copy everything from the local Postgres into the database in DATABASE_URL
(i.e. Supabase, after scripts/connect_supabase.py has pointed .env at it).

Safe to re-run: rows that already exist on the target are skipped.

Run:  .venv/bin/python -m scripts.migrate_to_supabase
"""
import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

LOCAL_URL = "postgresql+asyncpg://ibro@localhost:5432/sotuvchi_ai"

# Parent tables first — foreign keys must resolve as we go.
TABLES = [
    "tenants", "users", "tenant_settings", "categories", "products",
    "orders", "order_items", "conversations", "messages",
    "kb_documents", "kb_chunks",
]


async def fetch_all(engine, table):
    async with engine.connect() as conn:
        res = await conn.execute(text(f"SELECT * FROM {table}"))
        return [dict(r) for r in res.mappings().all()]


def _encode(value):
    """JSONB round-trip: the driver hands back list/dict but wants JSON text."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


async def copy_table(src_engine, dst_engine, table) -> tuple:
    rows = await fetch_all(src_engine, table)
    if not rows:
        return 0, 0

    cols = list(rows[0].keys())
    # search_text is GENERATED — Postgres computes it and rejects explicit values
    cols = [c for c in cols if c != "search_text"]
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)

    inserted = skipped = 0
    async with dst_engine.begin() as conn:
        for row in rows:
            payload = {c: _encode(row[c]) for c in cols}
            try:
                await conn.execute(
                    text(f'INSERT INTO {table} ({col_list}) VALUES ({placeholders}) '
                         f'ON CONFLICT DO NOTHING'),
                    payload,
                )
                inserted += 1
            except Exception as e:
                skipped += 1
                if skipped == 1:      # one sample is enough to diagnose
                    print(f"      ⚠️  {table}: {str(e)[:150]}")
    return inserted, skipped


async def fix_sequences(dst_engine) -> None:
    """Re-point autoincrement counters, else the first insert collides."""
    async with dst_engine.begin() as conn:
        for table in ("messages", "order_items", "kb_chunks"):
            await conn.execute(text(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1),
                    true
                )
            """))


async def main() -> None:
    dst_url = settings.DATABASE_URL
    if "localhost" in dst_url:
        print("❌ DATABASE_URL hali ham mahalliy bazani ko'rsatyapti.")
        print("   Avval: .venv/bin/python -m scripts.connect_supabase")
        sys.exit(1)

    print(f"  Manba : {LOCAL_URL}")
    print(f"  Manzil: {dst_url.split('@')[-1]}\n")

    src = create_async_engine(LOCAL_URL)
    dst = create_async_engine(dst_url, connect_args={"statement_cache_size": 0})

    try:
        # The target must already have the schema
        async with dst.connect() as conn:
            n = (await conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='tenants'"
            ))).scalar()
        if not n:
            print("❌ Manzil bazada jadvallar yo'q. Avval: .venv/bin/alembic upgrade head")
            sys.exit(1)

        total = 0
        for table in TABLES:
            ins, skip = await copy_table(src, dst, table)
            total += ins
            mark = "·" if ins == 0 else "✅"
            print(f"  {mark} {table:<18} {ins} qator" + (f"  ({skip} o'tkazildi)" if skip else ""))

        await fix_sequences(dst)

        print(f"\n  Jami ko'chirildi: {total} qator")
        async with dst.connect() as conn:
            r = await conn.execute(text("""
                SELECT t.business_name,
                       (SELECT count(*) FROM products p WHERE p.tenant_id=t.id) AS prod,
                       (SELECT count(*) FROM orders o WHERE o.tenant_id=t.id) AS ord
                FROM tenants t ORDER BY t.created_at
            """))
            print("\n  Supabase dagi holat:")
            for row in r:
                d = dict(row._mapping)
                print(f"    {d['business_name']:<24} {d['prod']} mahsulot, {d['ord']} buyurtma")
        print("\n  ✅ Tayyor. Endi serverni qayta ishga tushiring: ./run.sh\n")
    finally:
        await src.dispose()
        await dst.dispose()


if __name__ == "__main__":
    asyncio.run(main())
