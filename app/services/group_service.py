"""
Telegram team groups — the order pipeline after the AI closes a sale.

Flow:
  AI creates order
    → receipt posted to the ORDERS group with a "Tasdiqlash" button
    → first team member to tap confirms it (recorded; later taps are refused)
    → the confirmed order, with address and map pin, goes to the WORK group

Why pairing instead of a link: an invite link (t.me/+hash) is not a chat_id.
A bot can only message a group it has been added to, and it learns the id from
an update sent inside that group — hence the /guruh pairing command.
"""
import logging
import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, Tenant
from app.services.bot_service import bot_service

logger = logging.getLogger("group_service")

# panel key -> (tenant id column, tenant title column, human label)
GROUP_KINDS = {
    "buyurtmalar": ("orders_group_id", "orders_group_title", "Buyurtmalar guruhi"),
    "ishchi":      ("work_group_id", "work_group_title", "Ishchi guruh"),
    "operatorlar": ("operators_group_id", "operators_group_title", "Operatorlar guruhi"),
}


def generate_pairing_code() -> str:
    return secrets.token_hex(3).upper()


def _fmt_items(order: Order) -> str:
    return "\n".join(
        f"• {i.product_name} × {i.quantity} — {i.unit_price * i.quantity:,.0f}"
        for i in order.items
    )


# ─── Receipt into the orders group ────────────────────────────────────────────
async def send_order_receipt(session: AsyncSession, tenant: Tenant, order: Order) -> bool:
    """Post the order with a confirm button. Returns False if not configured."""
    if not tenant.telegram_bot_token or not tenant.orders_group_id:
        return False

    text = (
        "🧾 *YANGI BUYURTMA*\n"
        f"`{order.id}`\n\n"
        f"👤 {order.customer_name}\n"
        f"📞 {order.customer_phone}\n\n"
        f"{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
    )
    if order.delivery_address:
        text += f"📍 {order.delivery_address}\n"
    if order.latitude and order.longitude:
        text += "🗺 Lokatsiya biriktirilgan\n"
    text += "\n⏳ _Tasdiqlanmagan_"

    keyboard = {"inline_keyboard": [[
        {"text": "✅ Tasdiqlash", "callback_data": f"confirm:{order.id}"}
    ]]}

    msg = await bot_service.send_message_full(
        tenant.telegram_bot_token, tenant.orders_group_id, text, reply_markup=keyboard
    )
    if msg and msg.get("message_id"):
        order.receipt_message_id = str(msg["message_id"])
        await session.commit()
        return True

    logger.warning(f"Order receipt not delivered for tenant {tenant.id}")
    return False


# ─── Confirmation from the group ──────────────────────────────────────────────
async def confirm_order(
    session: AsyncSession, tenant: Tenant, order_id: str, who: str
) -> tuple:
    """Mark an order confirmed. Returns (ok, message-for-the-tapper)."""
    order = await session.get(Order, order_id)
    if not order or order.tenant_id != tenant.id:
        return False, "Buyurtma topilmadi"

    if order.confirmed_at:
        # Someone got here first — say who, and change nothing
        return False, f"Allaqachon tasdiqlangan: {order.confirmed_by}"

    from datetime import datetime, timezone
    order.confirmed_at = datetime.now(timezone.utc)
    order.confirmed_by = who
    order.status = "Tasdiqlandi"
    await session.commit()

    # Rewrite the receipt so the group sees it's handled and can't re-tap
    if order.receipt_message_id:
        await _mark_receipt_confirmed(tenant, order)

    await send_to_work_group(session, tenant, order)
    return True, f"✅ Tasdiqladingiz: {order.id}"


async def _mark_receipt_confirmed(tenant: Tenant, order: Order) -> None:
    text = (
        "🧾 *BUYURTMA*\n"
        f"`{order.id}`\n\n"
        f"👤 {order.customer_name}\n"
        f"📞 {order.customer_phone}\n\n"
        f"{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
    )
    if order.delivery_address:
        text += f"📍 {order.delivery_address}\n"
    text += f"\n✅ *Tasdiqladi: {order.confirmed_by}*"

    await bot_service.edit_message(
        tenant.telegram_bot_token, tenant.orders_group_id,
        order.receipt_message_id, text, reply_markup={"inline_keyboard": []},
    )


# ─── Handoff to the fulfilment group ──────────────────────────────────────────
async def send_to_work_group(session: AsyncSession, tenant: Tenant, order: Order) -> bool:
    """Everything the courier needs, plus the map pin as a real location."""
    target = tenant.work_group_id or tenant.orders_group_id
    if not tenant.telegram_bot_token or not target:
        return False

    text = (
        "📦 *YETKAZISHGA TAYYOR*\n"
        f"`{order.id}`\n\n"
        f"👤 *Ism:* {order.customer_name}\n"
        f"📞 *Telefon:* `{order.customer_phone}`\n"
        f"📍 *Manzil:* {order.delivery_address or '—'}\n\n"
        f"{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
        f"✅ Tasdiqladi: {order.confirmed_by}"
    )
    ok = await bot_service.send_message(tenant.telegram_bot_token, target, text)

    # A pinned location is far more useful to a courier than a text address
    if order.latitude and order.longitude:
        await bot_service.send_location(
            tenant.telegram_bot_token, target, order.latitude, order.longitude
        )
    return ok


# ─── Pairing a group ──────────────────────────────────────────────────────────
async def try_pair_group(
    session: AsyncSession, tenant: Tenant, kind: str, code: str,
    chat_id: str, chat_title: str,
) -> Optional[str]:
    """Handle '/guruh <kind> <code>' sent inside a group."""
    kind = (kind or "").strip().lower()
    if kind not in GROUP_KINDS:
        return ("❌ Guruh turi noto'g'ri.\nTo'g'ri variantlar: "
                + ", ".join(f"`{k}`" for k in GROUP_KINDS))

    if not tenant.group_pairing_code or code.strip().upper() != tenant.group_pairing_code.upper():
        return "❌ Kod noto'g'ri yoki eskirgan.\nPaneldan yangi kod oling."

    id_col, title_col, label = GROUP_KINDS[kind]
    setattr(tenant, id_col, str(chat_id))
    setattr(tenant, title_col, chat_title or kind)
    tenant.group_pairing_code = None      # single use
    await session.commit()

    extra = {
        "buyurtmalar": "Yangi buyurtmalar cheki shu yerga tushadi. Tasdiqlash tugmasi bilan.",
        "ishchi": "Tasdiqlangan buyurtmalar yetkazish uchun shu yerga keladi.",
        "operatorlar": "Mijoz operator so'raganda xabar shu yerga keladi.",
    }[kind]
    return f"✅ *{label}* ulandi!\n\n{extra}"
