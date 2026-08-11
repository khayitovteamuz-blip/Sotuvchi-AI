"""
Operator notifications — the piece that makes handoff actually work.

Marking a conversation "operator" only helps if a human finds out. Businesses
here live in Telegram, so alerts go to the owner's own Telegram chat: they get a
push on their phone the moment the AI escalates or an order lands.

Pairing: the panel shows a code, the owner sends "/operator <code>" to their bot,
and that chat becomes the alert destination.
"""
import logging
import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Order, Tenant, TenantSettings
from app.services.bot_service import bot_service

logger = logging.getLogger("notify_service")

CHANNEL_LABEL = {"telegram": "Telegram", "web": "Web chat", "instagram": "Instagram"}


def generate_pairing_code() -> str:
    """Short, readable, unguessable-enough pairing code."""
    return secrets.token_hex(3).upper()  # e.g. "A3F91C"


async def notify_handoff(
    session: AsyncSession,
    tenant: Tenant,
    cfg: TenantSettings,
    conversation: Conversation,
    reason: str,
    last_customer_message: str = "",
) -> bool:
    """Ping the operator that a customer is waiting for a human."""
    # A paired operator chat OR a team group is enough — either can be on duty
    if not cfg.notify_on_handoff or not tenant.telegram_bot_token:
        return False
    if not cfg.operator_chat_id and not tenant.operators_group_id:
        return False

    customer = conversation.customer_name or "Mijoz"
    channel = CHANNEL_LABEL.get(conversation.channel, conversation.channel)
    text = (
        "🔔 *Operator kerak!*\n\n"
        f"👤 Mijoz: *{customer}*\n"
        f"📱 Kanal: {channel}\n"
        f"❓ Sabab: {reason}\n"
    )
    if last_customer_message:
        text += f"\n💬 Oxirgi xabar:\n_{last_customer_message[:200]}_\n"
    text += "\n➡️ Panelda *Inbox* bo'limini oching va javob yozing."

    # Reaches whoever is on duty: the paired operator chat and/or the team group
    targets = [t for t in (cfg.operator_chat_id, tenant.operators_group_id) if t]
    if not targets:
        return False
    ok = False
    for target in targets:
        ok = await bot_service.send_message(tenant.telegram_bot_token, target, text) or ok
    if not ok:
        logger.warning(f"Handoff alert failed for tenant {tenant.id}")
    return ok


async def notify_customer_waiting(
    session: AsyncSession,
    tenant: Tenant,
    cfg: TenantSettings,
    conversation: Conversation,
    text: str,
) -> bool:
    """Customer wrote while a human owns the chat — the operator must know."""
    if not cfg.notify_on_handoff or not cfg.operator_chat_id or not tenant.telegram_bot_token:
        return False
    # Don't ping the operator about their own chat
    if str(conversation.external_id) == str(cfg.operator_chat_id):
        return False

    customer = conversation.customer_name or "Mijoz"
    body = (
        f"💬 *{customer}* yozdi (operator kutmoqda):\n\n"
        f"_{text[:250]}_\n\n"
        "➡️ Panelda *Inbox* dan javob bering."
    )
    return await bot_service.send_message(tenant.telegram_bot_token, cfg.operator_chat_id, body)


async def notify_new_order(
    session: AsyncSession, tenant: Tenant, cfg: TenantSettings, order: Order
) -> bool:
    """Ping the operator that a new order came in."""
    if not cfg.notify_on_order or not cfg.operator_chat_id or not tenant.telegram_bot_token:
        return False

    items = "\n".join(f"• {i.product_name} × {i.quantity}" for i in order.items)
    text = (
        "🎉 *Yangi buyurtma!*\n\n"
        f"🆔 `{order.id}`\n"
        f"👤 {order.customer_name}\n"
        f"📞 {order.customer_phone}\n"
        f"{items}\n"
        f"💰 *{order.total_amount:,.0f} UZS*\n"
    )
    if order.delivery_address:
        text += f"📍 {order.delivery_address}\n"
    text += "\n➡️ Panelda *Buyurtmalar* bo'limida ko'ring."

    ok = await bot_service.send_message(tenant.telegram_bot_token, cfg.operator_chat_id, text)
    if not ok:
        logger.warning(f"Order alert failed for tenant {tenant.id}")
    return ok


async def try_pair_operator(
    session: AsyncSession, tenant: Tenant, cfg: TenantSettings, chat_id: str, code: str, name: str
) -> Optional[str]:
    """Validate a pairing code and register this chat for alerts.

    Returns a message to send back to the sender, or None if the code is wrong
    (we stay silent then, so the code can't be brute-forced by chatting).
    """
    if not cfg.pairing_code or code.strip().upper() != cfg.pairing_code.upper():
        return None

    cfg.operator_chat_id = str(chat_id)
    cfg.operator_name = name
    cfg.pairing_code = None  # single use
    await session.commit()

    return (
        "✅ *Operator ulandi!*\n\n"
        f"Endi *{tenant.business_name}* bo'yicha bildirishnomalar shu chatga keladi:\n"
        "• AI operatorga uzatganda\n"
        "• Yangi buyurtma tushganda"
    )
