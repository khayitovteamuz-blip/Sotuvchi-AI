"""Who is on the other end of the chat.

The problem this solves: the same person writing from Telegram today and from
the web widget tomorrow used to be two unrelated rows, and "what has this
customer bought before?" — the most common question in a sale — had no answer.

Two keys resolve identity, deliberately in this order:

1. **Channel handle** (a Telegram chat id) — known from the first hello, but
   only ever identifies one channel.
2. **Phone number** — known once they order, and the same across every channel.
   This is the key that actually merges people, which is why an order is the
   moment a customer record gets stitched together.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Customer, CustomerIdentity, Order

logger = logging.getLogger("customer_service")

UZ_CODE = "998"
UZ_LOCAL_LEN = 9   # 90 123 45 67 without the country code


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """One canonical form, or None if there is no usable number in there.

    "+998 90 123 45 67", "998901234567" and "901234567" are the same person;
    without this they were three separate customers in every report.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == UZ_LOCAL_LEN:
        digits = UZ_CODE + digits
    elif len(digits) == UZ_LOCAL_LEN + 1 and digits.startswith("8"):
        # Sometimes typed with the old trunk prefix: 8 90 123 45 67
        digits = UZ_CODE + digits[1:]
    # Anything too short to dial is noise, not a number
    if len(digits) < 9:
        return None
    return "+" + digits


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _by_phone(session: AsyncSession, tenant_id: str, phone: str) -> Optional[Customer]:
    return (
        await session.execute(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.phone == phone)
        )
    ).scalars().first()


async def _by_identity(
    session: AsyncSession, tenant_id: str, channel: str, external_id: str
) -> Optional[Customer]:
    row = (
        await session.execute(
            select(CustomerIdentity).where(
                CustomerIdentity.tenant_id == tenant_id,
                CustomerIdentity.channel == channel,
                CustomerIdentity.external_id == str(external_id),
            )
        )
    ).scalars().first()
    return await session.get(Customer, row.customer_id) if row else None


async def resolve(
    session: AsyncSession,
    tenant_id: str,
    channel: str,
    external_id: Optional[str],
    name: Optional[str] = None,
    phone: Optional[str] = None,
    telegram_username: Optional[str] = None,
) -> Optional[Customer]:
    """Find or create the person behind this conversation.

    Called on every inbound message, so it must be cheap and must never raise:
    failing to identify a customer is not a reason to drop their message.
    """
    phone = normalize_phone(phone)
    customer = None
    if external_id:
        customer = await _by_identity(session, tenant_id, channel, str(external_id))
    if customer is None and phone:
        customer = await _by_phone(session, tenant_id, phone)

    if customer is None:
        customer = Customer(
            id=f"cus-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            name=(name or "").strip() or None,
            phone=phone,
            telegram_username=telegram_username,
        )
        session.add(customer)
        await session.flush()
    else:
        # Fill in blanks; never overwrite what the shop already knows with less.
        if phone and not customer.phone:
            existing = await _by_phone(session, tenant_id, phone)
            if existing is not None and existing.id != customer.id:
                await merge(session, keep=existing, absorb=customer)
                customer = existing
            else:
                customer.phone = phone
        if name and not customer.name:
            customer.name = name.strip()
        if telegram_username and not customer.telegram_username:
            customer.telegram_username = telegram_username
        customer.last_seen_at = _now()

    if external_id:
        known = await _by_identity(session, tenant_id, channel, str(external_id))
        if known is None:
            session.add(CustomerIdentity(
                tenant_id=tenant_id,
                customer_id=customer.id,
                channel=channel,
                external_id=str(external_id),
            ))
    return customer


async def merge(session: AsyncSession, keep: Customer, absorb: Customer) -> None:
    """Fold one record into another once a phone number proves they are one person.

    Everything is re-pointed rather than copied, so no history is lost: the
    orders, the conversations and the channel handles all move across.
    """
    if keep.id == absorb.id:
        return
    for table, column in (
        (CustomerIdentity, CustomerIdentity.customer_id),
        (Conversation, Conversation.customer_id),
        (Order, Order.customer_id),
    ):
        await session.execute(
            update(table).where(column == absorb.id).values(customer_id=keep.id)
        )
    keep.name = keep.name or absorb.name
    keep.telegram_username = keep.telegram_username or absorb.telegram_username
    keep.note = keep.note or absorb.note
    keep.first_seen_at = min(keep.first_seen_at, absorb.first_seen_at)
    keep.orders_count += absorb.orders_count
    keep.total_spent += absorb.total_spent
    await session.delete(absorb)
    logger.info(f"Merged customer {absorb.id} into {keep.id}")


async def record_order(session: AsyncSession, tenant_id: str, order: Order) -> Optional[Customer]:
    """Attach an order to its customer and refresh the running totals.

    An order is where a phone number first appears, so it is also where a
    Telegram-only record becomes a person the shop can recognise anywhere.
    """
    conv = await session.get(Conversation, order.conversation_id) if order.conversation_id else None
    customer = await resolve(
        session,
        tenant_id,
        channel=conv.channel if conv else "manual",
        external_id=(conv.external_id if conv else None) or order.telegram_id,
        name=order.customer_name,
        phone=order.customer_phone,
        telegram_username=order.customer_username,
    )
    if customer is None:
        return None

    order.customer_id = customer.id
    if conv is not None and conv.customer_id != customer.id:
        conv.customer_id = customer.id

    # Recounted rather than incremented: a merge, a deletion or a retry would
    # otherwise leave the totals drifting away from the orders they describe.
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0.0), func.count())
            .where(Order.customer_id == customer.id, Order.status != "Bekor qilindi")
        )
    ).first()
    customer.orders_count = count or 0
    customer.total_spent = float(total or 0)
    customer.last_seen_at = _now()
    return customer


async def refresh_totals(session: AsyncSession, customer_id: str) -> None:
    """Re-derive one customer's totals — after a status change or a deletion."""
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0.0), func.count())
            .where(Order.customer_id == customer_id, Order.status != "Bekor qilindi")
        )
    ).first()
    customer.orders_count = count or 0
    customer.total_spent = float(total or 0)
