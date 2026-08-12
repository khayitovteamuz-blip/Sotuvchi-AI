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

# Fallbacks only — the real numbers come from the tenant's Knowledge Base.
# A business that hasn't filled it in gets no invented prices: calc_delivery
# says "operator will confirm" instead of quoting a figure we made up.
DEFAULT_DELIVERY_DAYS_CITY = "1-2 kun"
DEFAULT_DELIVERY_DAYS_REGIONS = "2-4 kun"


# ─── Tool specs (one source, three renderings) ────────────────────────────────
# Written as plain JSON Schema because Gemini, Claude and ChatGPT each want a
# different wrapper around the same thing. Keeping one list means a tool can
# never exist for one provider and be quietly missing on another — the moment
# the shop switches model, the guardrails switch with it.
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "search_product",
        "description": (
            "Do'kon katalogidan mahsulot qidirish. Narx, tavsif yoki mavjudlik "
            "haqida gapirishdan OLDIN majburiy chaqiriladi. "
            "Faqat kalit so'z yuboring ('iphone', 'noutbuk'), butun jumlani emas. "
            "Filtrlardan foydalaning: mijoz 'arzonroq' desa max_price, "
            "'faqat bor bo'lganlari' desa in_stock_only."
        ),
        "properties": {
            "query": {"type": "string", "description": "Mahsulot nomi yoki kategoriya kalit so'zi. Bo'sh bo'lsa — katalog ko'rsatiladi."},
            "category": {"type": "string", "description": "Aniq kategoriya nomi (ixtiyoriy)"},
            "min_price": {"type": "number", "description": "Eng past narx, UZS (ixtiyoriy)"},
            "max_price": {"type": "number", "description": "Eng yuqori narx, UZS (ixtiyoriy)"},
            "in_stock_only": {"type": "boolean", "description": "Faqat omborda bor mahsulotlar"},
        },
    },
    {
        "name": "list_categories",
        "description": (
            "Katalogdagi kategoriyalar ro'yxatini olish (har birida nechta mahsulot "
            "va narx oralig'i). Mijoz 'nima bor?' deb so'raganda yoki katalog katta "
            "bo'lganda so'rovni toraytirish uchun ishlating."
        ),
        "properties": {},
    },
    {
        "name": "send_product_photo",
        "description": (
            "Mahsulot(lar) rasmini mijozga yuborish. Mijoz mahsulotga qiziqqanda, "
            "'rasmini ko'rsating' desa, yoki bir nechta variantni taqqoslaganda ishlating. "
            "Maksimal 4 ta. Rasm yuborgandan keyin matnda uni takrorlab tasvirlamang."
        ),
        "properties": {
            "product_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "search_product qaytargan mahsulot ID lari",
            },
        },
        "required": ["product_ids"],
    },
    {
        "name": "check_stock",
        "description": "Aniq mahsulotning omborda bor-yo'qligini va sonini tekshirish. Sotishdan oldin majburiy.",
        "properties": {
            "product_id": {"type": "string", "description": "search_product qaytargan mahsulot ID (masalan PROD-101)"},
        },
        "required": ["product_id"],
    },
    {
        "name": "calc_delivery",
        "description": "Yetkazib berish narxi va muddatini hisoblash.",
        "properties": {
            "region": {"type": "string", "description": "Manzil/viloyat (masalan 'Toshkent' yoki 'Samarqand')"},
            "order_amount": {"type": "number", "description": "Buyurtma summasi (UZS)"},
        },
        "required": ["region"],
    },
    {
        "name": "create_order",
        "description": (
            "Haqiqiy buyurtma yaratish. FAQAT mijoz ismi VA telefon raqamini bergan bo'lsa, "
            "hamda mahsulot omborda mavjud bo'lsa chaqiring. Buyurtma ID ni o'zingiz o'ylab topmang."
        ),
        "properties": {
            "customer_name": {"type": "string", "description": "Mijozning ismi"},
            "customer_phone": {"type": "string", "description": "Telefon raqami (+998...)"},
            "product_id": {"type": "string", "description": "Mahsulot ID"},
            "quantity": {"type": "integer", "description": "Soni (standart 1)"},
            "delivery_address": {"type": "string", "description": "Yetkazib berish manzili"},
        },
        "required": ["customer_name", "customer_phone", "product_id"],
    },
    {
        "name": "search_knowledge",
        "description": (
            "Do'kon qoidalarini bilish: to'lov turlari, kafolat, qaytarish siyosati, "
            "ish vaqti, yetkazib berish shartlari va boshqa FAQ. "
            "Mahsulotdan TASHQARI har qanday savolda MAJBURIY chaqiring — "
            "javobni o'zingizdan o'ylab topmang."
        ),
        "properties": {
            "question": {"type": "string", "description": "Mijozning savoli"},
        },
        "required": ["question"],
    },
    {
        "name": "handoff_to_human",
        "description": (
            "Suhbatni jonli operatorga uzatish. Mijoz operator so'raganda, shikoyat qilganda, "
            "yoki siz javobni bilmaganingizda chaqiring."
        ),
        "properties": {
            "reason": {"type": "string", "description": "Uzatish sababi"},
        },
        "required": ["reason"],
    },
]

_GEMINI_TYPES = {
    "string": types.Type.STRING,
    "number": types.Type.NUMBER,
    "integer": types.Type.INTEGER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _gemini_schema(node: Dict[str, Any]) -> types.Schema:
    kwargs: Dict[str, Any] = {"type": _GEMINI_TYPES[node["type"]]}
    if node.get("description"):
        kwargs["description"] = node["description"]
    if node.get("properties") is not None:
        kwargs["properties"] = {k: _gemini_schema(v) for k, v in node["properties"].items()}
    if node.get("items"):
        kwargs["items"] = _gemini_schema(node["items"])
    if node.get("required"):
        kwargs["required"] = node["required"]
    return types.Schema(**kwargs)


def tool_declarations() -> List[types.Tool]:
    """Gemini form."""
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=s["name"],
            description=s["description"],
            parameters=_gemini_schema({
                "type": "object",
                "properties": s["properties"],
                "required": s.get("required"),
            }),
        )
        for s in TOOL_SPECS
    ])]


def _json_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": spec["properties"],
        "required": spec.get("required", []),
    }


def anthropic_tools() -> List[Dict[str, Any]]:
    """Claude form: the schema lives under `input_schema`."""
    return [
        {"name": s["name"], "description": s["description"], "input_schema": _json_schema(s)}
        for s in TOOL_SPECS
    ]


def openai_tools() -> List[Dict[str, Any]]:
    """ChatGPT form: a `function` envelope with the schema under `parameters`."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": _json_schema(s),
            },
        }
        for s in TOOL_SPECS
    ]


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
            return await _calc_delivery(session, tenant_id, args.get("region", ""), args.get("order_amount"))
        if name == "search_knowledge":
            return await _search_knowledge(session, tenant_id, args.get("question", ""))
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


async def _calc_delivery(session, tenant_id: str, region: str, order_amount: Optional[float]) -> Dict[str, Any]:
    """Delivery terms come from the business's Knowledge Base, never from us."""
    cfg = await repo.get_settings(session, tenant_id)

    r = (region or "").lower()
    is_city = any(w in r for w in ("toshkent", "tashkent", "shahar"))
    fee = cfg.delivery_fee_city if is_city else cfg.delivery_fee_regions
    days = ((cfg.delivery_days_city or DEFAULT_DELIVERY_DAYS_CITY) if is_city
            else (cfg.delivery_days_regions or DEFAULT_DELIVERY_DAYS_REGIONS))

    # Not configured: say so plainly rather than quoting an invented price
    if fee is None:
        return {
            "region": region,
            "known": False,
            "message": ("Yetkazib berish narxi tizimda ko'rsatilmagan. Mijozga aniq narx "
                        "aytmang — 'operatorimiz aniq narxni aytadi' deng."),
            "estimated_days": days,
            "extra": cfg.delivery_info or None,
        }

    threshold = cfg.free_delivery_from
    free = bool(threshold and order_amount and order_amount >= threshold)
    return {
        "region": region,
        "known": True,
        "delivery_fee": 0 if free else float(fee),
        "currency": "UZS",
        "estimated_days": days,
        "free_delivery": free,
        "note": (f"{threshold:,.0f} UZS dan yuqori buyurtmalarga bepul." if free else None),
        "extra": cfg.delivery_info or None,
    }


async def _search_knowledge(session, tenant_id: str, question: str) -> Dict[str, Any]:
    """Answer policy questions from the tenant's own Knowledge Base."""
    cfg = await repo.get_settings(session, tenant_id)

    sections = {
        "to'lov": cfg.payment_info,
        "kafolat": cfg.warranty_info,
        "qaytarish": cfg.return_policy,
        "ish vaqti": cfg.working_hours,
        "yetkazib berish": cfg.delivery_info,
        "savol-javob": cfg.faq,
    }
    filled = {k: v for k, v in sections.items() if (v or "").strip()}

    if not filled:
        return {
            "found": False,
            "message": ("Bilimlar bazasi bo'sh. Javobni o'ylab topmang — "
                        "handoff_to_human bilan operatorga uzating."),
        }

    q = (question or "").lower()
    # Return the whole KB when nothing matches: it is short, and a policy answer
    # is worse than useless if it's the wrong section.
    hits = {k: v for k, v in filled.items() if k in q or any(w in (v or "").lower() for w in q.split() if len(w) > 3)}
    return {"found": True, "knowledge": hits or filled}


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
    await _post_order_receipt(session, tenant_id, order)

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


async def _post_order_receipt(session, tenant_id: str, order) -> bool:
    """Put the receipt in the orders group. Never break the sale over it."""
    try:
        from app.db.models import Tenant
        from app.services import group_service

        tenant = await session.get(Tenant, tenant_id)
        return await group_service.send_order_receipt(session, tenant, order)
    except Exception as e:
        logger.error(f"Order receipt failed: {e}")
        return False


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
