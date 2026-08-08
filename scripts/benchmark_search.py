"""
Load-test the catalog search: seed N products into a throwaway tenant, time the
queries, then clean up. Proves the search stays flat as the catalog grows.

Run:  .venv/bin/python -m scripts.benchmark_search 1000
"""
import asyncio
import statistics
import sys
import time

from sqlalchemy import text

from app.db.base import AsyncSessionLocal, engine
from app.db.models import Product, Tenant
from app.db import repo

BENCH_TENANT = "tenant-benchmark"

BRANDS = ["iPhone", "Samsung Galaxy", "Xiaomi Redmi", "MacBook", "Lenovo ThinkPad", "Asus VivoBook",
          "AirPods", "JBL", "Sony WH", "Apple Watch", "Amazfit", "Huawei Band", "Dyson", "Philips",
          "LG", "Bosch", "Artel", "Samsung QLED", "Canon", "Nikon"]
MODELS = ["Pro Max", "Ultra", "Lite", "Plus", "Air", "Mini", "SE", "Note", "Edge", "Prime"]
CATEGORIES = ["Smartfonlar", "Noutbuklar", "Aksessuarlar", "Aqlli soatlar", "Maishiy texnika",
              "Televizorlar", "Fotoapparatlar", "Audio texnika"]

QUERIES = [
    ("iphone", "aniq brend"),
    ("ayfon", "xato yozilgan"),
    ("noutbuklar", "ko'plik qo'shimchasi"),
    ("noutbukni", "tushum kelishigi"),
    ("smartfon", "kategoriya"),
    ("quloqchin", "topilmaydigan so'z"),
    ("samsung galaxy", "ikki so'z"),
    ("makbuk", "xato + brend"),
]


async def seed(start: int, end: int) -> None:
    async with AsyncSessionLocal() as s:
        if not await s.get(Tenant, BENCH_TENANT):
            s.add(Tenant(id=BENCH_TENANT, business_name="Benchmark Do'kon"))
            await s.flush()
        for i in range(start, end):
            brand = BRANDS[i % len(BRANDS)]
            model = MODELS[(i // len(BRANDS)) % len(MODELS)]
            s.add(Product(
                id=f"BENCH-{i:05d}",
                tenant_id=BENCH_TENANT,
                name=f"{brand} {model} {2020 + (i % 6)} {64 * (1 + i % 8)}GB",
                category=CATEGORIES[i % len(CATEGORIES)],
                price=float(500_000 + (i * 37_000) % 25_000_000),
                description=f"Yuqori sifatli {brand} mahsuloti, rasmiy kafolat bilan. "
                            f"Model {model}, ishlab chiqarilgan yil {2020 + (i % 6)}.",
                in_stock=(i % 7 != 0),
                stock_quantity=(i % 15),
            ))
            if i % 200 == 199:
                await s.commit()
        await s.commit()


async def bench(label: str) -> None:
    async with AsyncSessionLocal() as s:
        total = await repo.product_count(s, BENCH_TENANT)
        print(f"\n{'=' * 62}\n  {label}: {total:,} ta mahsulot\n{'=' * 62}")
        print("  {:<18} {:<22} {:>9}  natija".format("so'rov", "izoh", "vaqt"))
        for q, note in QUERIES:
            times = []
            rows, matched = [], True
            for _ in range(5):
                t0 = time.perf_counter()
                rows, found, matched = await repo.search_products(s, BENCH_TENANT, query=q, limit=8)
                times.append((time.perf_counter() - t0) * 1000)
            med = statistics.median(times)
            verdict = (rows[0]["name"][:34] if rows else "—") if matched else "TOPILMADI (muqobil taklif)"
            count = f"{len(rows)} ta" if matched else "0 ta"
            print(f"  {q:<18} {note:<22} {med:>6.1f} ms  {count} | {verdict}")

        # filtered browse (category + price range + in stock)
        t0 = time.perf_counter()
        rows, found, _ = await repo.search_products(
            s, BENCH_TENANT, query="", category="Smartfonlar",
            max_price=5_000_000, in_stock_only=True, limit=12)
        ms = (time.perf_counter() - t0) * 1000
        print(f"\n  filtr (kategoriya + narx + omborda bor): {ms:.1f} ms — {found} ta mos, {len(rows)} ko'rsatildi")

        t0 = time.perf_counter()
        cats = await repo.category_summary(s, BENCH_TENANT)
        print(f"  kategoriya xulosasi: {(time.perf_counter() - t0) * 1000:.1f} ms — {len(cats)} kategoriya")


async def cleanup() -> None:
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": BENCH_TENANT})


async def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    await cleanup()
    for size, label in ((100, "Kichik katalog"), (target, "Katta katalog")):
        async with AsyncSessionLocal() as s:
            have = await repo.product_count(s, BENCH_TENANT)
        if size > have:
            await seed(have, size)
        await bench(label)
    await cleanup()
    await engine.dispose()
    print("\n✅ Benchmark tugadi, test ma'lumotlari tozalandi.\n")


if __name__ == "__main__":
    asyncio.run(main())
