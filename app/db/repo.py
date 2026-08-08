"""
Async data-access layer — every function is tenant-scoped.

This is the single place that talks to Postgres for business data. API routes,
the AI agent and the bot all go through here, so tenant isolation is enforced
in one spot instead of scattered across the app.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Category,
    Conversation,
    Message,
    Order,
    OrderItem,
    Product,
    TenantSettings,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Products ─────────────────────────────────────────────────────────────────
async def list_products(session: AsyncSession, tenant_id: str) -> List[Product]:
    res = await session.execute(
        select(Product).where(Product.tenant_id == tenant_id).order_by(Product.created_at.desc())
    )
    return list(res.scalars().all())


async def get_product(session: AsyncSession, tenant_id: str, product_id: str) -> Optional[Product]:
    return await session.get(Product, {"tenant_id": tenant_id, "id": product_id})


# ─── Catalog search (trigram, index-backed) ───────────────────────────────────
_SEARCH_SQL = text("""
WITH scored AS (
    SELECT p.id, p.name, p.category, p.price, p.currency, p.description,
           p.in_stock, p.stock_quantity,
           GREATEST(
               similarity(sotuvchi_norm(p.name), :qn),
               CASE WHEN sotuvchi_norm(p.name) LIKE :pat THEN 0.92 ELSE 0 END,
               similarity(sotuvchi_norm(p.category), :qn) * 0.7,
               CASE WHEN sotuvchi_norm(p.category) LIKE :pat THEN 0.6 ELSE 0 END,
               CASE WHEN p.search_text LIKE :pat THEN 0.35 ELSE 0 END
           ) AS score
    FROM products p
    WHERE p.tenant_id = :tenant_id
      AND (p.search_text LIKE :pat
           OR sotuvchi_norm(p.name) % :qn
           OR sotuvchi_norm(p.category) % :qn)
      AND (CAST(:category AS text) IS NULL OR sotuvchi_norm(p.category) = sotuvchi_norm(CAST(:category AS text)))
      AND (CAST(:min_price AS float8) IS NULL OR p.price >= CAST(:min_price AS float8))
      AND (CAST(:max_price AS float8) IS NULL OR p.price <= CAST(:max_price AS float8))
      AND (NOT CAST(:in_stock_only AS boolean) OR (p.in_stock AND p.stock_quantity > 0))
)
SELECT *, count(*) OVER () AS total_matches
FROM scored
WHERE score > 0.12
ORDER BY score DESC, price ASC
LIMIT :limit
""")

_BROWSE_SQL = text("""
SELECT p.id, p.name, p.category, p.price, p.currency, p.description,
       p.in_stock, p.stock_quantity, 0.0 AS score,
       count(*) OVER () AS total_matches
FROM products p
WHERE p.tenant_id = :tenant_id
  AND (CAST(:category AS text) IS NULL OR sotuvchi_norm(p.category) = sotuvchi_norm(CAST(:category AS text)))
  AND (CAST(:min_price AS float8) IS NULL OR p.price >= CAST(:min_price AS float8))
  AND (CAST(:max_price AS float8) IS NULL OR p.price <= CAST(:max_price AS float8))
  AND (NOT CAST(:in_stock_only AS boolean) OR (p.in_stock AND p.stock_quantity > 0))
ORDER BY p.price ASC
LIMIT :limit
""")


def _normalize_query(q: str) -> str:
    """Same normalisation as the SQL sotuvchi_norm() function."""
    out = (q or "").lower()
    for ch in "ʻʼ‘’`´'\"":
        out = out.replace(ch, "")
    return out.strip()


# Uzbek/Russian phonetic spellings of common brands and product words.
# Trigram matching handles typos ("iphonee") but NOT transliteration: "ayfon"
# and "iphone" share almost no trigrams, yet customers type it constantly.
# Each entry lists the spellings worth trying, in order — a generic Uzbek word
# like "quloqchin" has no single canonical form across shops, so we try the
# Russian term and the dominant brand names too.
_ALIASES = {
    "ayfon": ["iphone"], "ayfone": ["iphone"], "iphon": ["iphone"], "ayphone": ["iphone"],
    "makbuk": ["macbook"], "mekbuk": ["macbook"], "makbook": ["macbook"],
    "samsun": ["samsung"], "samsang": ["samsung"],
    "shaomi": ["xiaomi"], "syaomi": ["xiaomi"], "ksiaomi": ["xiaomi"], "xiomi": ["xiaomi"],
    "aypod": ["airpods"], "erpods": ["airpods"], "airpod": ["airpods"],
    "noutbuk": ["noutbook", "macbook", "laptop"], "notebuk": ["noutbook"],
    "laptop": ["noutbook", "macbook"],
    "kompyuter": ["komputer", "pc"], "kampyuter": ["komputer"],
    "planshet": ["tablet", "ipad"], "planshyet": ["tablet"],
    "quloqchin": ["naushnik", "airpods", "quloqchin", "headphone"],
    "quloqchinlar": ["naushnik", "airpods"], "eshitgich": ["naushnik", "airpods"],
    "naushnik": ["airpods", "quloqchin", "headphone"],
    "muzlatgich": ["xolodilnik"], "changyutgich": ["pilesos"],
    "telefon": ["smartfon", "iphone", "samsung"], "tilfon": ["smartfon"],
    "soat": ["watch", "smart soat"],
}


def _aliases_for(qn: str) -> List[str]:
    """Alternative spellings to try when a query finds nothing."""
    if qn in _ALIASES:
        return list(_ALIASES[qn])
    # token-wise for multi-word queries ("ayfon 15 pro" -> "iphone 15 pro")
    tokens = qn.split()
    swapped = [_ALIASES.get(t, [t])[0] for t in tokens]
    if swapped != tokens:
        return [" ".join(swapped)]
    return []


# Words that carry no product meaning — never worth searching on their own.
_STOPWORDS = {
    "uchun", "bilan", "va", "yoki", "bor", "bormi", "narxi", "qancha", "necha",
    "menga", "kerak", "olmoqchiman", "olaman", "yaxshi", "eng", "ham", "bu",
    "qanday", "nima", "mahsulot", "model", "yangi", "arzon", "qimmat",
}


def _tokens_for_retry(qn: str) -> List[str]:
    """Meaningful tokens, longest first — used when a whole phrase finds nothing.

    A customer typing "soch uchun uskuna" should still reach the hair styler
    even though that exact phrase appears nowhere in the catalog.
    """
    tokens = [t for t in qn.split() if len(t) >= 4 and t not in _STOPWORDS]
    return sorted(set(tokens), key=len, reverse=True)[:3]


async def search_products(
    session: AsyncSession,
    tenant_id: str,
    query: str = "",
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock_only: bool = False,
    limit: int = 8,
) -> tuple:
    """Ranked catalog search. Returns (rows, total, matched).

    `matched` is False when the query found nothing and the rows are just a
    browse fallback — the caller must not present those as search results.

    Runs entirely in Postgres against GIN trigram indexes, so response time is
    flat whether the tenant has 12 products or 100 000.
    """
    params = {
        "tenant_id": tenant_id, "category": category,
        "min_price": min_price, "max_price": max_price,
        "in_stock_only": in_stock_only, "limit": limit,
    }
    qn = _normalize_query(query)
    if qn:
        params.update({"qn": qn, "pat": f"%{qn}%"})
        res = await session.execute(_SEARCH_SQL, params)
        rows = res.mappings().all()
        if rows:
            return rows, rows[0]["total_matches"], True

        # Miss: retry with the canonical spelling ("ayfon" -> "iphone"), then
        # with individual keywords ("soch uchun uskuna" -> "uskuna"). Retries
        # only run on a miss, so the common path stays a single indexed query.
        for candidate in _aliases_for(qn) + _tokens_for_retry(qn):
            params.update({"qn": candidate, "pat": f"%{candidate}%"})
            res = await session.execute(_SEARCH_SQL, params)
            rows = res.mappings().all()
            if rows:
                return rows, rows[0]["total_matches"], True

        # Still nothing — browse so the AI can offer alternatives
        res = await session.execute(_BROWSE_SQL, params)
        rows = res.mappings().all()
        return rows, (rows[0]["total_matches"] if rows else 0), False

    res = await session.execute(_BROWSE_SQL, params)
    rows = res.mappings().all()
    return rows, (rows[0]["total_matches"] if rows else 0), True


async def category_summary(session: AsyncSession, tenant_id: str) -> List[dict]:
    """Category names with counts and price range — how a big catalog is offered."""
    res = await session.execute(text("""
        SELECT category, count(*) AS n, min(price) AS min_price, max(price) AS max_price
        FROM products
        WHERE tenant_id = :tenant_id AND coalesce(category,'') <> ''
        GROUP BY category
        ORDER BY n DESC
        LIMIT 25
    """), {"tenant_id": tenant_id})
    return [dict(r) for r in res.mappings().all()]


async def product_count(session: AsyncSession, tenant_id: str) -> int:
    res = await session.execute(
        select(func.count()).select_from(Product).where(Product.tenant_id == tenant_id)
    )
    return res.scalar() or 0


async def create_product(session: AsyncSession, tenant_id: str, data: dict) -> Product:
    p = Product(
        id=data.get("id") or f"PROD-{uuid.uuid4().hex[:8].upper()}",
        tenant_id=tenant_id,
        name=data.get("name", ""),
        category=data.get("category", ""),
        price=float(data.get("price", 0)),
        currency=data.get("currency", "UZS"),
        description=data.get("description", ""),
        image_url=data.get("image_url"),
        image_urls=data.get("image_urls") or [],
        in_stock=data.get("in_stock", True),
        stock_quantity=int(data.get("stock_quantity", 10)),
        sku=data.get("sku"),
    )
    session.add(p)
    await session.commit()
    return p


async def update_product(session: AsyncSession, tenant_id: str, product_id: str, data: dict) -> Optional[Product]:
    p = await get_product(session, tenant_id, product_id)
    if not p:
        return None
    for field in ("name", "category", "price", "currency", "description",
                  "image_url", "image_urls", "in_stock", "stock_quantity", "sku"):
        if field in data and data[field] is not None:
            setattr(p, field, data[field])
    await session.commit()
    return p


async def delete_product(session: AsyncSession, tenant_id: str, product_id: str) -> bool:
    p = await get_product(session, tenant_id, product_id)
    if not p:
        return False
    await session.delete(p)
    await session.commit()
    return True


# ─── Categories ───────────────────────────────────────────────────────────────
async def list_categories(session: AsyncSession, tenant_id: str) -> List[dict]:
    res = await session.execute(select(Category).where(Category.tenant_id == tenant_id))
    cats = list(res.scalars().all())

    # product counts grouped by category name (products store category as text)
    cres = await session.execute(
        select(Product.category, func.count()).where(Product.tenant_id == tenant_id).group_by(Product.category)
    )
    counts = {(name or "").lower(): n for name, n in cres.all()}

    out = []
    for c in cats:
        out.append({
            "id": c.id, "name": c.name, "icon": c.icon,
            "image_url": c.image_url, "product_count": counts.get(c.name.lower(), 0),
        })
    return out


async def create_category(session: AsyncSession, tenant_id: str, data: dict) -> dict:
    c = Category(
        id=data.get("id") or f"cat-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        name=data.get("name", ""),
        icon=data.get("icon", "📁"),
        image_url=data.get("image_url"),
    )
    session.add(c)
    await session.commit()
    return {"id": c.id, "name": c.name, "icon": c.icon, "image_url": c.image_url, "product_count": 0}


async def update_category(session: AsyncSession, tenant_id: str, category_id: str, data: dict) -> Optional[dict]:
    c = await session.get(Category, category_id)
    if not c or c.tenant_id != tenant_id:
        return None
    old_name = c.name
    c.name = data.get("name", c.name)
    c.icon = data.get("icon", c.icon)
    c.image_url = data.get("image_url", c.image_url)
    # keep products in sync if the category was renamed
    if old_name.lower() != c.name.lower():
        pres = await session.execute(
            select(Product).where(Product.tenant_id == tenant_id, func.lower(Product.category) == old_name.lower())
        )
        for p in pres.scalars().all():
            p.category = c.name
    await session.commit()
    return {"id": c.id, "name": c.name, "icon": c.icon, "image_url": c.image_url, "product_count": 0}


async def delete_category(session: AsyncSession, tenant_id: str, category_id: str) -> bool:
    c = await session.get(Category, category_id)
    if not c or c.tenant_id != tenant_id:
        return False
    await session.delete(c)
    await session.commit()
    return True


# ─── Orders ───────────────────────────────────────────────────────────────────
async def list_orders(session: AsyncSession, tenant_id: str) -> List[Order]:
    res = await session.execute(
        select(Order).where(Order.tenant_id == tenant_id).order_by(Order.created_at.desc())
    )
    return list(res.scalars().all())


async def create_order(
    session: AsyncSession,
    tenant_id: str,
    customer_name: str,
    customer_phone: str,
    items: List[dict],
    telegram_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> Order:
    total = sum(float(i["unit_price"]) * int(i.get("quantity", 1)) for i in items)
    order = Order(
        id=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        tenant_id=tenant_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        telegram_id=telegram_id,
        conversation_id=conversation_id,
        total_amount=total,
        status="Yangi",
        delivery_address=delivery_address,
        notes=notes,
    )
    for i in items:
        order.items.append(OrderItem(
            product_id=i.get("product_id", ""),
            product_name=i.get("product_name", ""),
            quantity=int(i.get("quantity", 1)),
            unit_price=float(i["unit_price"]),
        ))
    session.add(order)
    await session.commit()
    return order


async def update_order_status(session: AsyncSession, tenant_id: str, order_id: str, status: str) -> Optional[Order]:
    o = await session.get(Order, order_id)
    if not o or o.tenant_id != tenant_id:
        return None
    o.status = status
    await session.commit()
    return o


# ─── Settings ─────────────────────────────────────────────────────────────────
async def get_settings(session: AsyncSession, tenant_id: str) -> TenantSettings:
    s = await session.get(TenantSettings, tenant_id)
    if not s:
        s = TenantSettings(tenant_id=tenant_id, system_prompt=settings.DEFAULT_SYSTEM_PROMPT)
        session.add(s)
        await session.commit()
    return s


async def save_settings(session: AsyncSession, tenant_id: str, data: dict) -> TenantSettings:
    s = await get_settings(session, tenant_id)
    for field in ("system_prompt", "ai_provider", "model_name", "temperature",
                  "bot_enabled", "sheets_sync_enabled", "ai_name", "ai_tone",
                  "ai_language", "greeting_message", "auto_handoff_after"):
        if field in data and data[field] is not None:
            setattr(s, field, data[field])
    await session.commit()
    return s


# ─── Conversations & Messages (Inbox backbone) ────────────────────────────────
async def get_or_create_conversation(
    session: AsyncSession,
    tenant_id: str,
    channel: str,
    external_id: str,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
) -> Conversation:
    res = await session.execute(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == channel,
            Conversation.external_id == external_id,
        )
    )
    conv = res.scalar_one_or_none()
    if conv:
        if customer_name and not conv.customer_name:
            conv.customer_name = customer_name
        if customer_phone and not conv.customer_phone:
            conv.customer_phone = customer_phone
        return conv

    conv = Conversation(
        id=f"conv-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        channel=channel,
        external_id=external_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        status="ai",
    )
    session.add(conv)
    await session.commit()
    return conv


async def add_message(
    session: AsyncSession,
    tenant_id: str,
    conversation: Conversation,
    sender: str,
    text: str,
    intent: Optional[str] = None,
    model_name: Optional[str] = None,
    tokens: int = 0,
    latency_ms: int = 0,
    meta: Optional[dict] = None,
) -> Message:
    m = Message(
        conversation_id=conversation.id,
        tenant_id=tenant_id,
        sender=sender,
        text=text,
        intent=intent,
        model_name=model_name,
        tokens=tokens,
        latency_ms=latency_ms,
        meta=meta,
    )
    session.add(m)
    conversation.last_message_at = _now()
    if sender in ("user",):
        conversation.unread_count = (conversation.unread_count or 0) + 1
    await session.commit()
    return m


async def recent_messages(session: AsyncSession, conversation_id: str, limit: int = 10) -> List[Message]:
    res = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(res.scalars().all()))


# ─── Inbox: conversation listing / detail / operator actions ──────────────────
async def list_conversations(session: AsyncSession, tenant_id: str, status: Optional[str] = None) -> List[dict]:
    q = select(Conversation).where(Conversation.tenant_id == tenant_id)
    if status and status != "all":
        q = q.where(Conversation.status == status)
    q = q.order_by(Conversation.last_message_at.desc()).limit(200)
    res = await session.execute(q)
    convs = list(res.scalars().all())

    # latest message text per conversation (one query, DISTINCT ON)
    previews: dict = {}
    if convs:
        ids = [c.id for c in convs]
        mres = await session.execute(
            select(Message.conversation_id, Message.text, Message.sender)
            .where(Message.conversation_id.in_(ids))
            .distinct(Message.conversation_id)
            .order_by(Message.conversation_id, Message.created_at.desc())
        )
        for cid, text, sender in mres.all():
            previews[cid] = {"text": text, "sender": sender}

    out = []
    for c in convs:
        pv = previews.get(c.id, {})
        # "waiting" = escalated to a human, and no human has replied yet.
        # The last message is usually the AI's "I'll connect you" line, so the
        # test is whether an operator has spoken — not who spoke last.
        waiting = c.status == "operator" and pv.get("sender") != "operator"
        out.append({
            "id": c.id, "channel": c.channel, "status": c.status,
            "customer_name": c.customer_name or "Mijoz",
            "customer_phone": c.customer_phone,
            "external_id": c.external_id,
            "unread_count": c.unread_count or 0,
            "last_message_at": c.last_message_at.strftime("%Y-%m-%d %H:%M") if c.last_message_at else None,
            "last_message": (pv.get("text") or "")[:80],
            "last_sender": pv.get("sender"),
            "assigned_user_name": c.assigned_user_name,
            "handoff_reason": c.handoff_reason,
            "waiting_for_operator": waiting,
        })
    return out


async def waiting_count(session: AsyncSession, tenant_id: str) -> int:
    """Conversations escalated to a human — the number that must not be ignored."""
    res = await session.execute(
        select(func.count()).select_from(Conversation).where(
            Conversation.tenant_id == tenant_id, Conversation.status == "operator"
        )
    )
    return res.scalar() or 0


async def get_conversation(session: AsyncSession, tenant_id: str, conv_id: str) -> Optional[Conversation]:
    c = await session.get(Conversation, conv_id)
    if not c or c.tenant_id != tenant_id:
        return None
    return c


async def conversation_messages(session: AsyncSession, conv_id: str) -> List[Message]:
    res = await session.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc())
    )
    return list(res.scalars().all())


async def set_conversation_status(session: AsyncSession, tenant_id: str, conv_id: str, status: str) -> Optional[Conversation]:
    c = await get_conversation(session, tenant_id, conv_id)
    if not c:
        return None
    c.status = status
    await session.commit()
    return c


async def mark_conversation_read(session: AsyncSession, tenant_id: str, conv_id: str) -> None:
    c = await get_conversation(session, tenant_id, conv_id)
    if c:
        c.unread_count = 0
        await session.commit()


# ─── Analytics ────────────────────────────────────────────────────────────────
async def analytics(session: AsyncSession, tenant_id: str) -> dict:
    # conversation counts by status
    cres = await session.execute(
        select(Conversation.status, func.count()).where(Conversation.tenant_id == tenant_id).group_by(Conversation.status)
    )
    by_status = {s: n for s, n in cres.all()}
    total_conv = sum(by_status.values())
    operator_conv = by_status.get("operator", 0) + by_status.get("closed", 0)

    # assistant response latency + token totals
    lres = await session.execute(
        select(func.avg(Message.latency_ms), func.sum(Message.tokens))
        .where(Message.tenant_id == tenant_id, Message.sender == "assistant")
    )
    avg_latency, total_tokens = lres.first()

    # message volume
    mres = await session.execute(
        select(func.count()).select_from(Message).where(Message.tenant_id == tenant_id)
    )
    total_messages = mres.scalar() or 0

    # orders / revenue
    ores = await session.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0)).where(Order.tenant_id == tenant_id)
    )
    order_count, revenue = ores.first()

    # Conversion = share of conversations that produced an order. Counting ALL
    # orders would exceed 100% (orders can exist without a conversation).
    cores = await session.execute(
        select(func.count(func.distinct(Order.conversation_id)))
        .where(Order.tenant_id == tenant_id, Order.conversation_id.isnot(None))
    )
    converted_conv = cores.scalar() or 0

    escalation_rate = round(operator_conv / total_conv * 100, 1) if total_conv else 0.0
    conversion_rate = round(converted_conv / total_conv * 100, 1) if total_conv else 0.0

    return {
        "total_conversations": total_conv,
        "by_status": {"ai": by_status.get("ai", 0), "operator": by_status.get("operator", 0), "closed": by_status.get("closed", 0)},
        "total_messages": total_messages,
        "avg_latency_ms": int(avg_latency or 0),
        "total_tokens": int(total_tokens or 0),
        "escalation_rate": escalation_rate,
        "conversion_rate": conversion_rate,
        "order_count": order_count or 0,
        "revenue": float(revenue or 0),
    }


# ─── Customers (aggregated from orders) ───────────────────────────────────────
async def list_customers(session: AsyncSession, tenant_id: str) -> List[dict]:
    res = await session.execute(
        select(
            Order.customer_phone,
            func.max(Order.customer_name),
            func.count(),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.max(Order.created_at),
        )
        .where(Order.tenant_id == tenant_id)
        .group_by(Order.customer_phone)
        .order_by(func.coalesce(func.sum(Order.total_amount), 0).desc())
    )
    out = []
    for phone, name, cnt, ltv, last in res.all():
        out.append({
            "customer_phone": phone, "customer_name": name or "Mijoz",
            "order_count": cnt, "ltv": float(ltv or 0),
            "last_order_at": last.strftime("%Y-%m-%d %H:%M") if last else None,
        })
    return out


# ─── Dashboard stats ──────────────────────────────────────────────────────────
async def dashboard_stats(session: AsyncSession, tenant_id: str) -> dict:
    orders = await list_orders(session, tenant_id)
    total_revenue = sum(o.total_amount for o in orders if o.status != "Bekor qilindi")
    total_orders = len(orders)

    conv_res = await session.execute(
        select(func.count()).select_from(Conversation).where(Conversation.tenant_id == tenant_id)
    )
    active_leads = conv_res.scalar() or 0
    conversion_rate = (total_orders / active_leads * 100) if active_leads > 0 else 0.0

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "active_leads": active_leads,
        "conversion_rate": round(conversion_rate, 1),
        "recent_orders": orders[:5],
    }
