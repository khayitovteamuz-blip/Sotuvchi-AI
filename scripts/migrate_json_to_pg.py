"""
One-shot migration: legacy JSON files  ->  Postgres.

Reads data/tenants/tenants.json and each tenant's products/orders/settings JSON,
then inserts Tenants, an owner User per tenant, TenantSettings, Categories
(derived from product categories), Products, Orders and OrderItems.

Idempotent: existing rows (by primary key) are skipped, so it is safe to re-run.
Run:  .venv/bin/python -m scripts.migrate_json_to_pg
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import BASE_DIR, settings
from app.db.base import AsyncSessionLocal
from app.db.models import (
    Category,
    Order,
    OrderItem,
    Product,
    Tenant,
    TenantSettings,
    User,
)

TENANTS_DIR = BASE_DIR / "data" / "tenants"

CATEGORY_ICONS = {
    "smartfonlar": "📱", "noutbuklar": "💻", "aksessuarlar": "🎧",
    "aqlli soatlar": "⌚️", "planshetlar": "📲", "kiyim": "👕",
    "kosmetika": "💄", "oziq-ovqat": "🛒", "mebel": "🛋",
}


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _load(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


async def migrate() -> None:
    tenants = _load(TENANTS_DIR / "tenants.json") or []
    created = {"tenants": 0, "users": 0, "settings": 0, "categories": 0, "products": 0, "orders": 0}

    async with AsyncSessionLocal() as s:
        for t in tenants:
            tid = t["id"]
            tenant_dir = TENANTS_DIR / tid

            # ── Tenant ──
            if not await s.get(Tenant, tid):
                s.add(Tenant(
                    id=tid,
                    business_name=t.get("business_name", "Biznes"),
                    is_active=t.get("is_active", True),
                    created_at=_parse_dt(t.get("created_at")) or datetime.now(timezone.utc),
                ))
                created["tenants"] += 1
                # Flush now so child rows (settings/products/categories/orders) can
                # satisfy their tenant_id FK — the ORM only auto-orders via
                # relationship(), and children here reference the tenant by column.
                await s.flush()

            # ── Owner user (auth moves from tenant -> user) ──
            existing_owner = await s.get(User, f"user-{tid}")
            if not existing_owner and t.get("email"):
                s.add(User(
                    id=f"user-{tid}",
                    tenant_id=tid,
                    email=t["email"],
                    password_hash=t.get("password_hash", ""),
                    role="owner",
                    full_name=t.get("business_name"),
                    created_at=_parse_dt(t.get("created_at")) or datetime.now(timezone.utc),
                ))
                created["users"] += 1

            # ── Settings ──
            if not await s.get(TenantSettings, tid):
                sj = _load(tenant_dir / "settings.json") or {}
                s.add(TenantSettings(
                    tenant_id=tid,
                    system_prompt=sj.get("system_prompt", settings.DEFAULT_SYSTEM_PROMPT),
                    ai_provider=sj.get("ai_provider", "gemini"),
                    model_name=sj.get("model_name", settings.GEMINI_CHAT_MODEL),
                    temperature=sj.get("temperature", 0.7),
                    bot_enabled=sj.get("bot_enabled", True),
                    sheets_sync_enabled=sj.get("sheets_sync_enabled", True),
                ))
                created["settings"] += 1

            # ── Products + derived Categories ──
            products = _load(tenant_dir / "products.json") or []
            seen_cats = {}
            for p in products:
                pid = p["id"]
                if not await s.get(Product, {"tenant_id": tid, "id": pid}):
                    img = p.get("image_url")
                    s.add(Product(
                        id=pid,
                        tenant_id=tid,
                        name=p.get("name", ""),
                        category=p.get("category", ""),
                        price=float(p.get("price", 0)),
                        currency=p.get("currency", "UZS"),
                        description=p.get("description", ""),
                        image_url=img,
                        image_urls=p.get("image_urls") or ([img] if img else []),
                        in_stock=p.get("in_stock", True),
                        stock_quantity=int(p.get("stock_quantity", 10)),
                    ))
                    created["products"] += 1
                cat = (p.get("category") or "").strip()
                if cat:
                    seen_cats.setdefault(cat.lower(), cat)

            # create one Category row per distinct product category
            for idx, (clow, cname) in enumerate(sorted(seen_cats.items()), start=1):
                cid = f"cat-{tid}-{idx}"
                if not await s.get(Category, cid):
                    s.add(Category(
                        id=cid, tenant_id=tid, name=cname,
                        icon=CATEGORY_ICONS.get(clow, "📦"),
                    ))
                    created["categories"] += 1

            # ── Orders + OrderItems ──
            orders = _load(tenant_dir / "orders.json") or []
            for o in orders:
                oid = o["id"]
                if await s.get(Order, oid):
                    continue
                order = Order(
                    id=oid,
                    tenant_id=tid,
                    customer_name=o.get("customer_name", "Mijoz"),
                    customer_phone=o.get("customer_phone", ""),
                    telegram_id=o.get("telegram_id"),
                    total_amount=float(o.get("total_amount", 0)),
                    status=o.get("status", "Yangi"),
                    delivery_address=o.get("delivery_address"),
                    notes=o.get("notes"),
                    created_at=_parse_dt(o.get("created_at")) or datetime.now(timezone.utc),
                )
                for it in o.get("items", []):
                    order.items.append(OrderItem(
                        product_id=it.get("product_id", ""),
                        product_name=it.get("product_name", ""),
                        quantity=int(it.get("quantity", 1)),
                        unit_price=float(it.get("unit_price", 0)),
                    ))
                s.add(order)
                created["orders"] += 1

        await s.commit()

    print("✅ Migratsiya tugadi. Qo'shildi:")
    for k, v in created.items():
        print(f"   • {k}: {v}")


if __name__ == "__main__":
    asyncio.run(migrate())
