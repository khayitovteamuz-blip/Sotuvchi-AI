"""Which alert goes where.

One question, one place to answer it. Before this, the destination was decided
inside each notification function — an escalation looked at `operator_chat_id`
and `operators_group_id`, an order looked only at `operator_chat_id`, a receipt
went to `orders_group_id` — so every alert the owner cared about arrived in the
same personal chat and nothing could be moved without a code change.

Now a destination is a paired chat (`NotifyChannel`) and the routing is data
(`TenantSettings.notify_routes`). Adding an event type means adding a row to
EVENTS below and reading it in the panel; it does not mean touching the sender.
"""
import logging
import secrets
import uuid
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotifyChannel, Tenant, TenantSettings

logger = logging.getLogger("routing")

# Every alert the bot can send, in the order the panel lists them.
#
# `needs_group` marks the two that carry buttons a team taps: a Telegram channel
# has no members to press them and no name to record as "who confirmed", so the
# panel refuses to route those there rather than letting a shop discover it when
# an order sits unconfirmed.
EVENTS: Dict[str, dict] = {
    "receipt": {
        "title": "Yangi buyurtma — to'lov kutilmoqda",
        "hint": "Mijoz, mahsulot, summa, to'lov cheki va «Tasdiqlash» tugmasi. "
                "Tugmani bosgan odamning ismi yozib olinadi.",
        "needs_group": True,
    },
    "delivery": {
        "title": "Yetkazishga tayyor",
        "hint": "To'lovi tasdiqlangan buyurtma: manzil va xarita nuqtasi bilan.",
        "needs_group": True,
    },
    "handoff": {
        "title": "Operator kerak",
        "hint": "AI javob topa olmadi yoki mijoz operator so'radi.",
        "needs_group": False,
    },
    "customer_waiting": {
        "title": "Mijoz kutmoqda",
        "hint": "Suhbat operatorda turganda mijoz yana yozdi.",
        "needs_group": False,
    },
    "billing": {
        "title": "Tarif va muddat",
        "hint": "Muddat tugashidan 7/3/1 kun oldin va tugaganda.",
        "needs_group": False,
    },
}
#
# There used to be a sixth, "Yangi buyurtma", sent the moment the AI closed a
# sale. It fired one line before the receipt for the same order, so every sale
# produced two notifications seconds apart — and the receipt already carries
# everything the first one did, plus the button. One order, one message.

KINDS = {"private": "Shaxsiy chat", "group": "Guruh", "channel": "Kanal"}


def new_code() -> str:
    """Short, readable, single-use pairing code."""
    return secrets.token_hex(3).upper()


async def channels(session: AsyncSession, tenant_id: str) -> List[NotifyChannel]:
    return list(
        (
            await session.execute(
                select(NotifyChannel)
                .where(NotifyChannel.tenant_id == tenant_id)
                .order_by(NotifyChannel.created_at)
            )
        ).scalars().all()
    )


async def add_channel(
    session: AsyncSession, tenant_id: str, chat_id: str, kind: str, title: str
) -> NotifyChannel:
    """Register a destination, or refresh the one already registered.

    Re-pairing the same chat must not create a duplicate: a shop that runs the
    command twice would otherwise receive every alert twice.
    """
    chat_id = str(chat_id)
    existing = (
        await session.execute(
            select(NotifyChannel).where(
                NotifyChannel.tenant_id == tenant_id, NotifyChannel.chat_id == chat_id
            )
        )
    ).scalars().first()
    if existing is not None:
        existing.kind = kind
        existing.title = title or existing.title
        return existing

    channel = NotifyChannel(
        id=f"nch-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        chat_id=chat_id,
        kind=kind,
        title=title or KINDS.get(kind, kind),
    )
    session.add(channel)
    return channel


async def remove_channel(session: AsyncSession, tenant_id: str, chat_id: str) -> bool:
    """Unpair a destination and drop it from every route it appears in.

    Leaving it in the routes would keep the panel showing a destination that no
    longer exists, and every send to it would fail silently.
    """
    channel = (
        await session.execute(
            select(NotifyChannel).where(
                NotifyChannel.tenant_id == tenant_id, NotifyChannel.chat_id == str(chat_id)
            )
        )
    ).scalars().first()
    if channel is None:
        return False

    cfg = await session.get(TenantSettings, tenant_id)
    if cfg is not None and cfg.notify_routes:
        routes = {
            event: [c for c in targets if str(c) != str(chat_id)]
            for event, targets in cfg.notify_routes.items()
        }
        cfg.notify_routes = {e: t for e, t in routes.items() if t}
    await session.delete(channel)
    return True


def targets_for(cfg: Optional[TenantSettings], event: str) -> List[str]:
    """Chat ids this event should reach. Empty means the shop switched it off."""
    if cfg is None or not cfg.notify_routes:
        return []
    raw = cfg.notify_routes.get(event) or []
    if isinstance(raw, str):        # tolerate a single id written by hand
        raw = [raw]
    return [str(c) for c in raw if c]


async def send(
    session: AsyncSession, tenant: Tenant, cfg: Optional[TenantSettings], event: str,
    text: str, reply_markup: Optional[dict] = None,
) -> bool:
    """Deliver one alert to every destination routed to it.

    True if it reached at least one place. A shop with two destinations on an
    event should not have the second suppressed because the first is misconfigured.
    """
    if not tenant.telegram_bot_token:
        return False
    from app.services.bot_service import bot_service

    ok = False
    for chat_id in targets_for(cfg, event):
        ok = await bot_service.send_message(
            tenant.telegram_bot_token, chat_id, text, reply_markup=reply_markup
        ) or ok
    if not ok and targets_for(cfg, event):
        logger.warning(f"Tenant {tenant.id}: '{event}' alert reached nobody")
    return ok


def default_routes(tenant: Tenant, cfg: TenantSettings) -> Dict[str, List[str]]:
    """Reproduce exactly where alerts went before routing existed.

    Used by the migration and by any tenant whose map is still empty, so turning
    this feature on changes nothing until the owner moves something.
    """
    operator = str(cfg.operator_chat_id) if cfg.operator_chat_id else None
    orders = str(tenant.orders_group_id) if tenant.orders_group_id else None
    work = str(tenant.work_group_id) if tenant.work_group_id else None
    operators = str(tenant.operators_group_id) if tenant.operators_group_id else None

    routes = {
        # The receipt is the new-order notification. Where no orders group was
        # paired it falls back to the owner's chat, which is where the old
        # separate "new order" ping used to land — so a shop without groups
        # still hears about a sale.
        "receipt": [orders or operator],
        # Delivery fell back to the orders group when no work group existed
        "delivery": [work or orders],
        # An escalation went to the owner AND the operators' group
        "handoff": [operator, operators],
        "customer_waiting": [operator],
        # Subscription notices fell back to the orders group when no operator
        # chat was paired
        "billing": [operator or orders],
    }
    return {event: [c for c in targets if c] for event, targets in routes.items()
            if [c for c in targets if c]}


async def ensure_routes(session: AsyncSession, tenant: Tenant, cfg: TenantSettings) -> None:
    """Fill an empty map from the old columns, once."""
    if cfg.notify_routes:
        return
    routes = default_routes(tenant, cfg)
    if routes:
        cfg.notify_routes = routes
        await session.commit()


async def try_pair(
    session: AsyncSession, tenant: Tenant, cfg: TenantSettings,
    chat_id: str, kind: str, title: str, code: str,
) -> Optional[str]:
    """Validate a pairing code and register this chat as a destination.

    Returns the reply to send back, or None when the code is wrong — silence
    then, so the code cannot be found by guessing at the bot in a chat.

    One command for every kind of destination. There used to be two (`/operator`
    for a personal chat, `/guruh <type>` for each named group), which meant the
    owner had to know at pairing time what a chat would be used for. That is now
    a separate choice, made in the panel and changeable afterwards.
    """
    entered = (code or "").strip().upper()
    valid = {c.upper() for c in (cfg.pairing_code, tenant.group_pairing_code) if c}
    if not entered or entered not in valid:
        return None

    channel = await add_channel(session, tenant.id, chat_id, kind, title)

    # A brand-new shop has no routes at all; its first destination should
    # receive everything rather than nothing, or the pairing looks broken.
    first = not cfg.notify_routes
    if first:
        cfg.notify_routes = {
            event: [channel.chat_id]
            for event, spec in EVENTS.items()
            if not spec["needs_group"] or kind != "private"
        }

    # Single use, both codes: a code that keeps working is a code anyone who
    # saw the screen can use on their own chat.
    cfg.pairing_code = None
    tenant.group_pairing_code = None
    if kind == "private" and not cfg.operator_chat_id:
        # Kept in step for the older columns still read by the panel's
        # "operator connected" badge.
        cfg.operator_chat_id = channel.chat_id
        cfg.operator_name = title
    await session.commit()

    where = KINDS.get(kind, kind).lower()
    if first:
        what = "Barcha bildirishnomalar shu yerga keladi."
    else:
        what = ("Panelda *Integratsiyalar → Bildirishnomalar* bo'limidan "
                "qaysi xabarlar shu yerga kelishini tanlang.")
    return (
        f"✅ *Ulandi!*\n\n"
        f"*{tenant.business_name}* — bu {where} endi bildirishnoma manzili.\n\n{what}"
    )
