"""
AI auto-categorisation.

An imported price list is usually a flat list of names — no categories, or
inconsistent ones ("tel", "Telefonlar", "SMARTFON"). A catalog like that is
unusable both for the customer browsing it and for the AI narrowing a big
catalog down. So: let the model read the product names and group them.

Runs in batches, reuses the tenant's existing category names where they fit,
and only ever writes a category — never a price or stock.
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Category, Product

logger = logging.getLogger("categorize_service")

BATCH_SIZE = 60          # products per model call
MAX_BATCHES = 6          # cap per run so one request can't burn the whole quota
CATEGORY_ICONS = {
    "smartfon": "📱", "telefon": "📱", "noutbuk": "💻", "kompyuter": "💻",
    "aksessuar": "🎧", "audio": "🔊", "quloqchin": "🎧", "soat": "⌚️",
    "planshet": "📲", "televizor": "📺", "maishiy": "🏠", "kiyim": "👕",
    "kosmetika": "💄", "parfyum": "🧴", "oziq": "🛒", "mebel": "🛋",
    "sport": "⚽️", "kitob": "📚", "o'yinchoq": "🧸", "foto": "📷",
}


def _icon_for(name: str) -> str:
    low = name.lower()
    for key, icon in CATEGORY_ICONS.items():
        if key in low:
            return icon
    return "📦"


def _client():
    try:
        from google import genai
        return genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Gemini client init failed: {e}")
        return None


def _classify_batch(client, model: str, items: List[Dict[str, str]], known: List[str]) -> Dict[str, str]:
    """Ask the model for {product_id: category}. Returns {} on failure."""
    from google.genai import types

    listing = "\n".join(f"{p['id']}|{p['name']}" for p in items)
    known_str = ", ".join(known) if known else "(hali yo'q)"

    prompt = f"""Quyidagi mahsulotlarni kategoriyalarga ajrating.

MAVJUD KATEGORIYALAR (imkon qadar shulardan foydalaning): {known_str}

QOIDALAR:
- Kategoriya nomi o'zbek tilida, ko'plikda bo'lsin ("Smartfonlar", "Noutbuklar").
- Mavjud kategoriya mos kelsa — aynan o'shani yozing, yangisini o'ylab topmang.
- Umumiy va tushunarli bo'lsin. Juda mayda bo'lmasin ("iPhone 15" emas, "Smartfonlar").
- Jami kategoriyalar soni 12 tadan oshmasin.
- HAR BIR mahsulot uchun javob qaytaring.

MAHSULOTLAR (format: id|nom):
{listing}"""

    schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "assignments": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "id": types.Schema(type=types.Type.STRING),
                        "category": types.Schema(type=types.Type.STRING),
                    },
                    required=["id", "category"],
                ),
            )
        },
        required=["assignments"],
    )

    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.1,   # classification, not creativity
            ),
        )
        data = json.loads(resp.text or "{}")
        return {
            a["id"]: a["category"].strip()
            for a in data.get("assignments", [])
            if a.get("id") and a.get("category")
        }
    except Exception as e:
        logger.error(f"Categorisation batch failed: {e}")
        return {}


async def auto_categorize(
    session: AsyncSession,
    tenant_id: str,
    only_uncategorized: bool = True,
) -> Dict[str, Any]:
    """Assign categories to a tenant's products using the model."""
    if not settings.GEMINI_API_KEY:
        return {"success": False, "error": "Gemini API kaliti sozlanmagan."}

    q = select(Product).where(Product.tenant_id == tenant_id)
    res = await session.execute(q)
    products = list(res.scalars().all())
    if only_uncategorized:
        products = [p for p in products if not (p.category or "").strip()]

    if not products:
        return {
            "success": True, "updated": 0, "new_categories": 0,
            "message": "Kategoriyasiz mahsulot yo'q — hammasi ajratilgan.",
        }

    cres = await session.execute(select(Category).where(Category.tenant_id == tenant_id))
    existing_cats = list(cres.scalars().all())
    known_names = [c.name for c in existing_cats]
    have = {c.name.strip().lower(): c for c in existing_cats}

    client = _client()
    if client is None:
        return {"success": False, "error": "Gemini clientini ishga tushirib bo'lmadi."}

    model = settings.GEMINI_CHAT_MODEL
    batches = [products[i:i + BATCH_SIZE] for i in range(0, len(products), BATCH_SIZE)]
    truncated = len(batches) > MAX_BATCHES
    batches = batches[:MAX_BATCHES]

    updated, new_categories = 0, 0
    assigned_names: set = set()

    for batch in batches:
        items = [{"id": p.id, "name": p.name} for p in batch]
        mapping = await asyncio.to_thread(_classify_batch, client, model, items, known_names)
        if not mapping:
            continue
        for p in batch:
            cat = mapping.get(p.id)
            if not cat:
                continue
            p.category = cat
            updated += 1
            assigned_names.add(cat)
        # let later batches reuse categories the earlier ones introduced
        for n in assigned_names:
            if n not in known_names:
                known_names.append(n)

    # Create Category rows for anything new, so the catalog UI groups them
    for name in sorted(assigned_names):
        if name.strip().lower() not in have:
            c = Category(
                id=f"cat-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id,
                name=name, icon=_icon_for(name),
            )
            session.add(c)
            have[name.strip().lower()] = c
            new_categories += 1

    await session.commit()

    return {
        "success": True,
        "updated": updated,
        "new_categories": new_categories,
        "categories": sorted(assigned_names),
        "remaining": max(0, len(products) - updated) if truncated else 0,
        "message": (
            f"{updated} ta mahsulot kategoriyalandi."
            + (" Qolganlari uchun qayta bosing." if truncated else "")
        ),
    }
