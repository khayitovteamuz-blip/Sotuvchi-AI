"""
AI tool-calling layer — what turns this from a chatbot into a sales agent.

The model never states a price, stock level or order id from its own head: it
must call one of these tools, and every value they return is read straight from
the tenant's Postgres rows. That is the guardrail.

Tools:
  search_product   — find products in THIS tenant's catalog
  check_stock      — authoritative availability + quantity
  create_order     — persist a real order (requires name + phone)
  calc_delivery    — delivery cost/time from tenant settings
  handoff_to_human — escalate to an operator (pauses the AI)
"""
import logging
import re
from typing import Any, Dict, List, Optional

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import Conversation

logger = logging.getLogger("ai_tools")

# Free delivery above this amount (kept here so the model can't invent its own rule)
FREE_DELIVERY_THRESHOLD = 1_000_000.0
DELIVERY_FEE_TASHKENT = 25_000.0
DELIVERY_FEE_REGIONS = 45_000.0


# ─── Declarations sent to Gemini ──────────────────────────────────────────────
def tool_declarations() -> List[types.Tool]:
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="search_product",
            description=(
                "Do'kon katalogidan mahsulot qidirish. Narx, tavsif yoki mavjudlik "
                "haqida gapirishdan OLDIN majburiy chaqiriladi. "
                "Faqat kalit so'z yuboring ('iphone', 'noutbuk'), butun jumlani emas. "
                "Filtrlardan foydalaning: mijoz 'arzonroq' desa max_price, "
                "'faqat bor bo'lganlari' desa in_stock_only."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Mahsulot nomi yoki kategoriya kalit so'zi. Bo'sh bo'lsa — katalog ko'rsatiladi."),
                    "category": types.Schema(type=types.Type.STRING, description="Aniq kategoriya nomi (ixtiyoriy)"),
                    "min_price": types.Schema(type=types.Type.NUMBER, description="Eng past narx, UZS (ixtiyoriy)"),
                    "max_price": types.Schema(type=types.Type.NUMBER, description="Eng yuqori narx, UZS (ixtiyoriy)"),
                    "in_stock_only": types.Schema(type=types.Type.BOOLEAN, description="Faqat omborda bor mahsulotlar"),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="list_categories",
            description=(
                "Katalogdagi kategoriyalar ro'yxatini olish (har birida nechta mahsulot "
                "va narx oralig'i). Mijoz 'nima bor?' deb so'raganda yoki katalog katta "
                "bo'lganda so'rovni toraytirish uchun ishlating."
            ),
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="send_product_photo",
            description=(
                "Mahsulot(lar) rasmini mijozga yuborish. Mijoz mahsulotga qiziqqanda, "
                "'rasmini ko'rsating' desa, yoki bir nechta variantni taqqoslaganda ishlating. "
                "Maksimal 4 ta. Rasm yuborgandan keyin matnda uni takrorlab tasvirlamang."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_ids": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="search_product qaytargan mahsulot ID lari",
                    ),
                },
                required=["product_ids"],
            ),
        ),
        types.FunctionDeclaration(
            name="check_stock",
            description="Aniq mahsulotning omborda bor-yo'qligini va sonini tekshirish. Sotishdan oldin majburiy.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "product_id": types.Schema(type=types.Type.STRING, description="search_product qaytargan mahsulot ID (masalan PROD-101)"),
                },
                required=["product_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="calc_delivery",
            description="Yetkazib berish narxi va muddatini hisoblash.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "region": types.Schema(type=types.Type.STRING, description="Manzil/viloyat (masalan 'Toshkent' yoki 'Samarqand')"),
                    "order_amount": types.Schema(type=types.Type.NUMBER, description="Buyurtma summasi (UZS)"),
                },
                required=["region"],
            ),
        ),
        types.FunctionDeclaration(
            name="create_order",
            description=(
                "Haqiqiy buyurtma yaratish. FAQAT mijoz ismi VA telefon raqamini bergan bo'lsa, "
                "hamda mahsulot omborda mavjud bo'lsa chaqiring. Buyurtma ID ni o'zingiz o'ylab topmang."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "customer_name": types.Schema(type=types.Type.STRING, description="Mijozning ismi"),
                    "customer_phone": types.Schema(type=types.Type.STRING, description="Telefon raqami (+998...)"),
                    "product_id": types.Schema(type=types.Type.STRING, description="Mahsulot ID"),
                    "quantity": types.Schema(type=types.Type.INTEGER, description="Soni (standart 1)"),
                    "delivery_address": types.Schema(type=types.Type.STRING, description="Yetkazib berish manzili"),
                },
                required=["customer_name", "customer_phone", "product_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="handoff_to_human",
            description=(
                "Suhbatni jonli operatorga uzatish. Mijoz operator so'raganda, shikoyat qilganda, "
                "yoki siz javobni bilmaganingizda chaqiring."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "reason": types.Schema(type=types.Type.STRING, description="Uzatish sababi"),
                },
                required=["reason"],
            ),
        ),
    ])]


# ─── Executors (the only source of truth) ─────────────────────────────────────
async def execute_tool(
    name: str,
    args: Dict[str, Any],
    session: AsyncSession,
    tenant_id: str,
    conversation: Conversation,
) -> Dict[str, Any]:
    """Run one tool call against Postgres and return a JSON-able result."""
    try:
        if name == "search_product":
            return await _search_product(session, tenant_id, args)
        if name == "list_categories":
            return await _list_categories(session, tenant_id)
        if name == "send_product_photo":
            return await _send_product_photo(session, tenant_id, args)
        if name == "check_stock":
            return await _check_stock(session, tenant_id, args.get("product_id", ""))
        if name == "calc_delivery":
            return _calc_delivery(args.get("region", ""), args.get("order_amount"))
        if name == "create_order":
            return await _create_order(session, tenant_id, conversation, args)
        if name == "handoff_to_human":
            return await _handoff(session, tenant_id, conversation, args.get("reason", ""))
        return {"error": f"Noma'lum funksiya: {name}"}
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return {"error": f"Funksiyani bajarishda xatolik: {e}"}


# How many products a single answer may carry. Every row returned lands in the
# model's context and costs tokens, so this is a cost/latency limit, not a DB one.
SEARCH_LIMIT = 8
BROWSE_LIMIT = 12
# Above this, dumping the catalog is useless to the customer — offer categories.
BIG_CATALOG = 25


async def _search_product(session, tenant_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or "").strip()
    category = (args.get("category") or "").strip() or None
    min_price = args.get("min_price")
    max_price = args.get("max_price")
    in_stock_only = bool(args.get("in_stock_only"))

    # No query and no filters on a large catalog: guide instead of dumping
    if not query and not category and min_price is None and max_price is None:
        total = await repo.product_count(session, tenant_id)
        if total > BIG_CATALOG:
            cats = await repo.category_summary(session, tenant_id)
            return {
                "catalog_size": total,
                "message": f"Katalogda {total} ta mahsulot bor — juda ko'p. Kategoriyalardan birini tanlang yoki mijozdan aniqroq so'rang.",
                "categories": [
                    {"name": c["category"], "count": c["n"],
                     "price_from": float(c["min_price"]), "price_to": float(c["max_price"])}
                    for c in cats
                ],
            }

    limit = SEARCH_LIMIT if query else BROWSE_LIMIT
    rows, total, matched = await repo.search_products(
        session, tenant_id, query=query, category=category,
        min_price=min_price, max_price=max_price,
        in_stock_only=in_stock_only, limit=limit,
    )

    # Nothing actually matched: never present the fallback rows as if the
    # searched product exists — that is how an AI ends up "selling" a product
    # the shop does not carry.
    if not matched:
        cats = await repo.category_summary(session, tenant_id)
        return {
            "found": 0,
            "message": f"'{query}' katalogda YO'Q. Mijozga buni ayting va quyidagi muqobillarni taklif qiling.",
            "alternatives": [_row_brief(r) for r in rows[:5]],
            "available_categories": [c["category"] for c in cats],
        }

    if not rows:
        cats = await repo.category_summary(session, tenant_id)
        return {
            "found": 0,
            "message": "Bu shartlarga mos mahsulot yo'q.",
            "available_categories": [c["category"] for c in cats],
        }

    out = {
        "found": total,
        "showing": len(rows),
        "products": [_row_brief(r) for r in rows],
    }
    if total > len(rows):
        out["note"] = (
            f"Jami {total} ta mos mahsulot bor, shundan {len(rows)} tasi ko'rsatildi. "
            "Mijozdan aniqroq so'rang (kategoriya yoki narx oralig'i)."
        )
    return out


def _row_brief(r) -> Dict[str, Any]:
    """Compact row for lists — description is omitted on purpose.

    Descriptions are the bulk of the tokens; the model gets the full text from
    check_stock once the customer picks a specific product.
    """
    return {
        "product_id": r["id"],
        "name": r["name"],
        "price": r["price"],
        "currency": r["currency"],
        "category": r["category"],
        "available": bool(r["in_stock"] and r["stock_quantity"] > 0),
    }


MAX_PHOTOS = 4


async def _send_product_photo(session, tenant_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Collect image URLs for the channel to deliver.

    The tool doesn't send anything itself — the agent is channel-agnostic, so it
    returns the photos and Telegram (or a future web widget) does the sending.
    """
    ids = args.get("product_ids") or []
    if isinstance(ids, str):
        ids = [ids]

    photos, missing = [], []
    for pid in ids[:MAX_PHOTOS]:
        p = await repo.get_product(session, tenant_id, str(pid).strip())
        if not p:
            missing.append(pid)
            continue
        url = (p.image_urls[0] if p.image_urls else None) or p.image_url
        if not url or not url.startswith("http"):
            missing.append(p.name)     # locally-uploaded images aren't reachable by Telegram
            continue
        photos.append({
            "url": url,
            "caption": f"*{p.name}*\n{p.price:,.0f} {p.currency}",
            "product_id": p.id,
        })

    if not photos:
        return {
            "sent": 0,
            "message": "Bu mahsulotlarda rasm yo'q. Mijozga matn bilan tasvirlab bering.",
            "missing": missing,
        }
    return {
        "sent": len(photos),
        "photos": photos,
        "message": f"{len(photos)} ta rasm mijozga yuborildi. Matnda qisqa izoh bering.",
        "missing": missing,
    }


async def _list_categories(session, tenant_id: str) -> Dict[str, Any]:
    cats = await repo.category_summary(session, tenant_id)
    total = await repo.product_count(session, tenant_id)
    if not cats:
        return {"categories": [], "catalog_size": total, "message": "Kategoriyalar hali qo'shilmagan."}
    return {
        "catalog_size": total,
        "categories": [
            {"name": c["category"], "count": c["n"],
             "price_from": float(c["min_price"]), "price_to": float(c["max_price"])}
            for c in cats
        ],
    }


async def _check_stock(session, tenant_id: str, product_id: str) -> Dict[str, Any]:
    p = await repo.get_product(session, tenant_id, product_id)
    if not p:
        return {"found": False, "message": f"'{product_id}' ID li mahsulot katalogda yo'q."}
    return {
        "found": True,
        "product_id": p.id,
        "name": p.name,
        "in_stock": p.in_stock and p.stock_quantity > 0,
        "stock_quantity": p.stock_quantity,
        "price": p.price,
        "currency": p.currency,
        "category": p.category,
        "description": p.description,  # full text lives here, not in search results
    }


def _calc_delivery(region: str, order_amount: Optional[float]) -> Dict[str, Any]:
    r = (region or "").lower()
    is_tashkent = "toshkent" in r or "tashkent" in r
    fee = DELIVERY_FEE_TASHKENT if is_tashkent else DELIVERY_FEE_REGIONS
    days = "1-2 kun" if is_tashkent else "2-4 kun"
    free = bool(order_amount and order_amount >= FREE_DELIVERY_THRESHOLD)
    return {
        "region": region,
        "delivery_fee": 0 if free else fee,
        "currency": "UZS",
        "estimated_days": days,
        "free_delivery": free,
        "note": (f"{FREE_DELIVERY_THRESHOLD:,.0f} UZS dan yuqori buyurtmalarga yetkazib berish bepul."
                 if free else None),
    }


async def _create_order(session, tenant_id: str, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("customer_name") or "").strip()
    phone = (args.get("customer_phone") or "").strip()
    product_id = (args.get("product_id") or "").strip()
    qty = int(args.get("quantity") or 1)

    # Guardrail: never invent a customer
    if not name or not phone:
        return {"success": False, "error": "Ism va telefon raqami majburiy. Mijozdan so'rang."}
    if not re.search(r"\d{7,}", phone):
        return {"success": False, "error": "Telefon raqami noto'g'ri ko'rinadi. Mijozdan aniqlashtiring."}

    # Guardrail: product and stock must be real
    p = await repo.get_product(session, tenant_id, product_id)
    if not p:
        return {"success": False, "error": f"'{product_id}' mahsuloti katalogda yo'q. search_product bilan tekshiring."}
    if not p.in_stock or p.stock_quantity < qty:
        return {"success": False, "error": f"'{p.name}' omborda yetarli emas (qoldiq: {p.stock_quantity}). Sotib bo'lmaydi."}

    order = await repo.create_order(
        session, tenant_id,
        customer_name=name,
        customer_phone=phone,
        items=[{"product_id": p.id, "product_name": p.name, "quantity": qty, "unit_price": p.price}],
        telegram_id=conversation.external_id if conversation.channel == "telegram" else None,
        conversation_id=conversation.id,
        delivery_address=args.get("delivery_address"),
        notes="AI Sotuvchi (tool-calling) orqali yaratildi",
    )
    # keep the customer on the conversation for the Inbox
    if not conversation.customer_phone:
        conversation.customer_phone = phone
    if not conversation.customer_name or conversation.customer_name == "Mijoz":
        conversation.customer_name = name
    await session.commit()

    await _alert_operator_order(session, tenant_id, order)

    return {
        "success": True,
        "order_id": order.id,
        "total_amount": order.total_amount,
        "currency": p.currency,
        "product_name": p.name,
        "quantity": qty,
        "customer_phone": phone,
    }


async def _handoff(session, tenant_id: str, conversation, reason: str) -> Dict[str, Any]:
    conversation.status = "operator"
    conversation.handoff_reason = reason
    await session.commit()

    # Alert a real human — a status change nobody sees is not a handoff
    notified = await _alert_operator_handoff(session, tenant_id, conversation, reason)

    return {
        "success": True,
        "message": (
            "Suhbat operatorga uzatildi va operatorga bildirishnoma yuborildi."
            if notified else
            "Suhbat operatorga uzatildi."
        ),
        "operator_notified": notified,
        "reason": reason,
    }


async def _alert_operator_order(session, tenant_id: str, order) -> bool:
    """Push a new-order alert. Never let a notification failure break the sale."""
    try:
        from app.db.models import Tenant
        from app.services import notify_service

        tenant = await session.get(Tenant, tenant_id)
        cfg = await repo.get_settings(session, tenant_id)
        return await notify_service.notify_new_order(session, tenant, cfg, order)
    except Exception as e:
        logger.error(f"Order notification failed: {e}")
        return False


async def _alert_operator_handoff(session, tenant_id: str, conversation, reason: str) -> bool:
    """Send the handoff push. Never let a notification failure break the chat."""
    try:
        from app.db.models import Tenant
        from app.services import notify_service

        tenant = await session.get(Tenant, tenant_id)
        cfg = await repo.get_settings(session, tenant_id)
        history = await repo.recent_messages(session, conversation.id, limit=6)
        last_user = next((m.text for m in reversed(history) if m.sender == "user"), "")
        return await notify_service.notify_handoff(
            session, tenant, cfg, conversation, reason, last_user
        )
    except Exception as e:
        logger.error(f"Handoff notification failed: {e}")
        return False
