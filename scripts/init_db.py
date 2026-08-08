"""
Create the database schema in Postgres.

Idempotent: enables pgvector, then create_all (skips existing tables).
Run:  .venv/bin/python -m scripts.init_db
"""
import asyncio

from sqlalchemy import text

from app.db.base import Base, engine
import app.db.models  # noqa: F401  (registers all models on Base.metadata)


async def main() -> None:
    async with engine.begin() as conn:
        # pgvector must exist before creating tables with Vector columns
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)

    # Report what exists now
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name;"
        ))
        tables = [r[0] for r in rows]
    await engine.dispose()

    print("✅ Schema tayyor. Jadvallar:")
    for t in tables:
        print("   •", t)


if __name__ == "__main__":
    asyncio.run(main())
