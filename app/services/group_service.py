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

from app.db import repo
from app.db.models import Order, Tenant
from app.services import routing_service
from app.services.bot_service import bot_service

logger = logging.getLogger("group_service")

# panel key -> (tenant id column, tenant title column, human label)
GROUP_KINDS = {
    "buyurtmalar": ("orders_group_id", "orders_group_title", "Chek guruhi (to'lov tasdiqlash)"),
    "ishchi":      ("work_group_id", "work_group_title", "Tayyor buyurtmalar guruhi"),
    "operatorlar": ("operators_group_id", "operators_group_title", "Operatorlar guruhi"),
}


def generate_pairing_code() -> str:
    return secrets.token_hex(3).upper()


def _contact_line(order: Order) -> str:
    """Telegram handle or chat id — a way back to the customer when the phone fails."""
    if order.customer_username:
        return f"💬 @{order.customer_username}\n"
    if order.telegram_id:
        return f"💬 Telegram ID: `{order.telegram_id}`\n"
    return ""


def _fmt_items(order: Order) -> str:
    return "\n".join(
        f"• {i.product_name} × {i.quantity} — {i.unit_price * i.quantity:,.0f}"
        for i in order.items
    )


# ─── Receipt into the orders group ────────────────────────────────────────────
async def send_order_receipt(session: AsyncSession, tenant: Tenant, order: Order) -> bool:
    """Post the order with a confirm button. Returns False if not configured."""
    cfg = await repo.get_settings(session, tenant.id)
    targets = routing_service.targets_for(cfg, "receipt")
    if not tenant.telegram_bot_token or not targets:
        return False

    text = (
        "🧾 *YANGI BUYURTMA — to'lov tekshirilsin*\n"
        f"`{order.id}`\n\n"
        f"👤 {order.customer_name}\n"
        f"📞 {order.customer_phone}\n"
        f"{_contact_line(order)}"
        f"\n{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
    )
    if order.delivery_address:
        text += f"📍 {order.delivery_address}\n"
    if order.latitude and order.longitude:
        text += "🗺 Lokatsiya biriktirilgan\n"
    text += "\n⏳ _To'lov kutilmoqda_"

    keyboard = {"inline_keyboard": [[
        {"text": "✅ To'lov tasdiqlandi", "callback_data": f"confirm:{order.id}"}
    ]]}

    # The team confirms payment against the slip, so it has to travel with the
    # receipt. Telegram re-sends by file_id, so nothing is re-uploaded.
    # The confirm button is a single-use action, so only the FIRST destination
    # keeps the button and has its message id recorded — the rest get the same
    # receipt without one. Two live buttons would let the same order be
    # confirmed twice by two different people.
    sent = False
    for i, target in enumerate(targets):
        markup = keyboard if i == 0 else None
        if order.payment_photo_file_id:
            msg = await bot_service.send_photo_full(
                tenant.telegram_bot_token, target,
                order.payment_photo_file_id, caption=text, reply_markup=markup,
            )
            if not msg:
                # Photo failed (bad id, too large) — still deliver it as text
                logger.warning("Payment slip could not be sent; falling back to text")
                msg = await bot_service.send_message_full(
                    tenant.telegram_bot_token, target, text, reply_markup=markup)
        else:
            msg = await bot_service.send_message_full(
                tenant.telegram_bot_token, target, text, reply_markup=markup)

        if msg and msg.get("message_id"):
            sent = True
            if i == 0:
                order.receipt_message_id = str(msg["message_id"])
                order.receipt_chat_id = str(target)
    if sent:
        await session.commit()
        return True

    logger.warning(f"Order receipt not delivered for tenant {tenant.id}")
    return False


async def attach_payment_slip(
    session: AsyncSession, tenant: Tenant, conversation_id: str, file_id: str
) -> bool:
    """Customer sent a payment slip: put it in front of the team.

    The order is created before the customer pays, so the first receipt has no
    slip. When the photo arrives we retire that message's button and repost the
    receipt as the photo itself — one order, one live button, slip attached.
    """
    from sqlalchemy import select

    res = await session.execute(
        select(Order)
        .where(
            Order.tenant_id == tenant.id,
            Order.conversation_id == conversation_id,
            Order.confirmed_at.is_(None),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    order = res.scalar_one_or_none()
    if not order:
        return False          # a photo unrelated to any pending order

    order.payment_photo_file_id = file_id
    await session.commit()

    # Retire the old button so only the slip version is actionable
    old_chat = order.receipt_chat_id or tenant.orders_group_id
    if order.receipt_message_id and old_chat:
        await bot_service.edit_message(
            tenant.telegram_bot_token, old_chat,
            order.receipt_message_id,
            f"🧾 `{order.id}` — _chek rasmi keldi, quyida_",
            reply_markup={"inline_keyboard": []},
        )
        order.receipt_message_id = None

    return await send_order_receipt(session, tenant, order)


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
        return False, f"To'lovni allaqachon tasdiqlagan: {order.confirmed_by}"

    from datetime import datetime, timezone
    order.confirmed_at = datetime.now(timezone.utc)
    order.confirmed_by = who
    order.status = "Tasdiqlandi"
    await session.commit()

    # Rewrite the receipt so the group sees it's handled and can't re-tap
    if order.receipt_message_id:
        await _mark_receipt_confirmed(tenant, order)

    await send_to_work_group(session, tenant, order)
    return True, f"✅ To'lov tasdiqlandi: {order.id}"


async def _mark_receipt_confirmed(tenant: Tenant, order: Order) -> None:
    text = (
        "🧾 *BUYURTMA*\n"
        f"`{order.id}`\n\n"
        f"👤 {order.customer_name}\n"
        f"📞 {order.customer_phone}\n"
        f"{_contact_line(order)}"
        f"\n{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
    )
    if order.delivery_address:
        text += f"📍 {order.delivery_address}\n"
    text += f"\n✅ *To'lov tasdiqlandi — {order.confirmed_by}*"

    # Photo receipts carry a caption; text receipts carry text
    # Where the receipt actually went — the routed destination, not a fixed
    # column, which could now be a different chat entirely.
    chat_id = order.receipt_chat_id or tenant.orders_group_id
    if not chat_id:
        return

    if order.payment_photo_file_id:
        ok = await bot_service.edit_caption(
            tenant.telegram_bot_token, chat_id,
            order.receipt_message_id, text, reply_markup={"inline_keyboard": []},
        )
        if ok:
            return

    await bot_service.edit_message(
        tenant.telegram_bot_token, chat_id,
        order.receipt_message_id, text, reply_markup={"inline_keyboard": []},
    )


# ─── Handoff to the fulfilment group ──────────────────────────────────────────
async def send_to_work_group(session: AsyncSession, tenant: Tenant, order: Order) -> bool:
    """Everything the courier needs, plus the map pin as a real location."""
    cfg = await repo.get_settings(session, tenant.id)
    targets = routing_service.targets_for(cfg, "delivery")
    if not tenant.telegram_bot_token or not targets:
        return False

    text = (
        "📦 *YETKAZISHGA TAYYOR*\n"
        f"`{order.id}`\n\n"
        f"👤 *Ism:* {order.customer_name}\n"
        f"📞 *Telefon:* `{order.customer_phone}`\n"
        f"{_contact_line(order)}"
        f"📍 *Manzil:* {order.delivery_address or '—'}\n\n"
        f"{_fmt_items(order)}\n\n"
        f"💰 *Jami: {order.total_amount:,.0f} UZS*\n"
        f"✅ To'lovni tasdiqladi: {order.confirmed_by}"
    )
    ok = False
    for target in targets:
        if order.payment_photo_file_id:
            sent = bool(await bot_service.send_photo_full(
                tenant.telegram_bot_token, target, order.payment_photo_file_id, caption=text))
            if not sent:
                sent = await bot_service.send_message(tenant.telegram_bot_token, target, text)
        else:
            sent = await bot_service.send_message(tenant.telegram_bot_token, target, text)
        ok = sent or ok

        # A pinned location is far more useful to a courier than a text address
        if sent and order.latitude and order.longitude:
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

    # Codes stay single-use, but hand out the next one right here — otherwise
    # connecting three groups means three trips back to the panel.
    tenant.group_pairing_code = generate_pairing_code()
    await session.commit()

    extra = {
        "buyurtmalar": "Yangi buyurtma cheki shu yerga tushadi — to'lovni tasdiqlash tugmasi bilan.",
        "ishchi": "To'lovi tasdiqlangan, yetkazishga tayyor buyurtmalar shu yerga keladi.",
        "operatorlar": "Mijoz operator so'raganda xabar shu yerga keladi.",
    }[kind]

    remaining = [
        f"`{k}`" for k in GROUP_KINDS
        if not getattr(tenant, GROUP_KINDS[k][0])
    ]
    nxt = ""
    if remaining:
        nxt = (f"\n\n➡️ Keyingi guruh uchun kod: `{tenant.group_pairing_code}`\n"
               f"Qolgan turlar: {', '.join(remaining)}")

    return f"✅ *{label}* ulandi!\n\n{extra}{nxt}"
