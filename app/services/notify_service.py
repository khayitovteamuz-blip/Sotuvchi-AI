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
from app.services import routing_service

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
    """Ping whoever is on duty that a customer is waiting for a human."""
    if not cfg.notify_on_handoff:
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

    return await routing_service.send(session, tenant, cfg, "handoff", text)


async def notify_customer_waiting(
    session: AsyncSession,
    tenant: Tenant,
    cfg: TenantSettings,
    conversation: Conversation,
    text: str,
) -> bool:
    """Customer wrote while a human owns the chat — the operator must know."""
    if not cfg.notify_on_handoff:
        return False
    # Don't ping a destination about its own chat: the owner's personal chat is
    # both a destination and, if they ever message the bot, a conversation.
    if str(conversation.external_id) in routing_service.targets_for(cfg, "customer_waiting"):
        return False

    customer = conversation.customer_name or "Mijoz"
    body = (
        f"💬 *{customer}* yozdi (operator kutmoqda):\n\n"
        f"_{text[:250]}_\n\n"
        "➡️ Panelda *Inbox* dan javob bering."
    )
    return await routing_service.send(session, tenant, cfg, "customer_waiting", body)


async def notify_new_order(
    session: AsyncSession, tenant: Tenant, cfg: TenantSettings, order: Order
) -> bool:
    """Ping whoever watches sales that a new order came in."""
    if not cfg.notify_on_order:
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

    return await routing_service.send(session, tenant, cfg, "order", text)


async def notify_subscription(
    session: AsyncSession, tenant: Tenant, plan, stage: int
) -> bool:
    """Tell the owner their period is ending — or has.

    Sent to whichever Telegram destination the business has already paired, so
    it lands as a phone notification rather than a banner nobody opens the
    panel to see. There is deliberately no email path: this product's customers
    live in Telegram and an email channel does not exist yet.
    """
    cfg = await session.get(TenantSettings, tenant.id)

    price = f"{float(plan.price_uzs):,.0f} so'm".replace(",", " ") if plan else ""
    title = plan.title if plan else tenant.plan

    if stage == 0:
        text = (
            "🔴 *Tarif muddati tugadi*\n\n"
            f"*{tenant.business_name}* — {title}\n"
            "Bot hozircha ishlayapti, lekin bir necha kundan keyin javob berishni "
            "to'xtatadi.\n\n"
            f"Panelda *Hisobim* bo'limidan hisobni to'ldiring va tarifni yangilang."
            + (f"\nTarif narxi: {price}" if price else "")
        )
    else:
        kun = {7: "7 kun", 3: "3 kun", 1: "1 kun"}.get(stage, f"{stage} kun")
        text = (
            "🟡 *Tarif muddati tugayapti*\n\n"
            f"*{tenant.business_name}* — {title}\n"
            f"Yana *{kun}* qoldi.\n\n"
            "Hisobda mablag' bo'lsa tarif avtomatik yangilanadi. "
            "Bo'lmasa — panelda *Hisobim* bo'limidan to'ldiring."
            + (f"\nTarif narxi: {price}" if price else "")
        )

    return await routing_service.send(session, tenant, cfg, "billing", text)


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
