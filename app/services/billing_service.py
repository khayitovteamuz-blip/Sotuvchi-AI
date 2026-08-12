"""
Balance, subscriptions and the payment ledger.

Three rules shape everything here:

1. A business can never credit its own balance. Topping up creates a *pending*
   row; only a platform admin confirming that the transfer arrived turns it into
   money. Otherwise the panel would be a free-money button.

2. A tariff runs for the plan's duration and then stops. Expiry is evaluated
   lazily — on panel access and on every AI turn — rather than by a timer,
   because a timer in one worker is a timer the other workers do not have.

3. Suspending a business stops its clock instead of spending it. `frozen_at`
   records the moment; resuming pushes the expiry forward by exactly how long
   the account sat idle, so unused days survive the suspension.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, Plan, Tenant

logger = logging.getLogger("billing")

# Whether a tier is free is decided by its price, not by its name. Naming one
# plan "free" in code meant that raising its price left it exempt from expiry —
# a paid tariff that never had to be renewed.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_free(plan: Optional[Plan]) -> bool:
    """A plan costing nothing has nothing to renew."""
    return plan is not None and float(plan.price_uzs or 0) <= 0


def days_left(tenant: Tenant) -> Optional[float]:
    """Days remaining, measured from the freeze point when suspended."""
    if tenant.subscription_expires_at is None:
        return None
    reference = tenant.frozen_at or _now()
    return max(0.0, (tenant.subscription_expires_at - reference).total_seconds() / 86400)


def status_of(tenant: Tenant, plan: Optional[Plan] = None) -> str:
    """frozen | expired | active | free — what the panels label the account.

    `plan` is optional because some callers already hold it; without it a
    tariff is assumed to be paid, which is the safe default now that every
    tier can carry a price.
    """
    if tenant.frozen_at is not None:
        return "frozen"
    if is_free(plan):
        return "free"
    left = days_left(tenant)
    if left is None:
        return "free"
    return "active" if left > 0 else "expired"


def freeze(tenant: Tenant) -> None:
    """Stop the subscription clock. Idempotent."""
    if tenant.frozen_at is None:
        tenant.frozen_at = _now()


def unfreeze(tenant: Tenant) -> None:
    """Resume, pushing the expiry forward by the paused duration."""
    if tenant.frozen_at is None:
        return
    if tenant.subscription_expires_at is not None:
        tenant.subscription_expires_at += _now() - tenant.frozen_at
    tenant.frozen_at = None


async def enforce_expiry(session: AsyncSession, tenant: Tenant) -> bool:
    """Deactivate a business whose paid period has run out.

    Returns True if this call changed anything. Checked wherever the tenant is
    already being loaded, so it costs no extra query.
    """
    if tenant.frozen_at is not None or not tenant.is_active:
        return False
    if tenant.subscription_expires_at is None:
        return False
    if is_free(await session.get(Plan, tenant.plan)):
        return False
    if tenant.subscription_expires_at > _now():
        return False

    tenant.is_active = False
    await session.commit()
    logger.warning(f"Tenant {tenant.id} subscription expired — deactivated")
    return True


async def summary(session: AsyncSession, tenant: Tenant) -> dict:
    plan = await session.get(Plan, tenant.plan)
    left = days_left(tenant)
    return {
        "balance": float(tenant.balance or 0),
        "plan": tenant.plan,
        "plan_title": plan.title if plan else tenant.plan,
        "plan_price": float(plan.price_uzs) if plan else 0.0,
        "duration_days": plan.duration_days if plan else 30,
        "status": status_of(tenant, plan),
        "is_active": tenant.is_active,
        "expires_at": (
            tenant.subscription_expires_at.strftime("%Y-%m-%d")
            if tenant.subscription_expires_at else None
        ),
        "days_left": round(left, 1) if left is not None else None,
        "frozen_at": tenant.frozen_at.strftime("%Y-%m-%d %H:%M") if tenant.frozen_at else None,
    }


async def request_topup(
    session: AsyncSession, tenant_id: str, amount: float, note: Optional[str] = None
) -> Payment:
    """Record a claimed transfer. Pending until an admin confirms it."""
    if amount <= 0:
        raise ValueError("Summa noldan katta bo'lishi kerak.")
    payment = Payment(
        id=f"pay-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        amount=float(amount),
        kind="topup",
        status="pending",
        note=(note or "").strip() or None,
    )
    session.add(payment)
    await session.commit()
    return payment


async def confirm_topup(
    session: AsyncSession, payment: Payment, tenant: Tenant, admin_email: str
) -> None:
    """Credit the balance. Guarded so a double-click cannot pay twice."""
    if payment.status != "pending":
        raise ValueError("Bu to'lov allaqachon ko'rib chiqilgan.")
    payment.status = "confirmed"
    payment.confirmed_at = _now()
    payment.confirmed_by = admin_email
    tenant.balance = float(tenant.balance or 0) + payment.amount
    await session.commit()


async def reject_topup(session: AsyncSession, payment: Payment, admin_email: str) -> None:
    if payment.status != "pending":
        raise ValueError("Bu to'lov allaqachon ko'rib chiqilgan.")
    payment.status = "rejected"
    payment.confirmed_at = _now()
    payment.confirmed_by = admin_email
    await session.commit()


async def adjust_balance(
    session: AsyncSession, tenant: Tenant, amount: float, admin_email: str, note: str
) -> Payment:
    """Manual correction — a refund, a goodwill credit, a bank fee.

    Written as a ledger row like everything else so the balance always adds up
    from its history.
    """
    payment = Payment(
        id=f"pay-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        amount=float(amount),
        kind="adjustment",
        status="confirmed",
        note=note.strip() or None,
        confirmed_at=_now(),
        confirmed_by=admin_email,
    )
    session.add(payment)
    tenant.balance = float(tenant.balance or 0) + float(amount)
    await session.commit()
    return payment


async def buy_plan(session: AsyncSession, tenant: Tenant, plan: Plan) -> dict:
    """Charge the balance and extend the subscription.

    Time is added to whatever is left rather than replacing it — renewing early
    must not cost the customer the days they already paid for.
    """
    price = float(plan.price_uzs or 0)
    if price > float(tenant.balance or 0):
        raise ValueError(
            f"Hisobda mablag' yetarli emas. Kerak: {price:,.0f} so'm, "
            f"mavjud: {float(tenant.balance or 0):,.0f} so'm."
        )

    now = _now()
    base = tenant.subscription_expires_at
    if tenant.frozen_at is not None:
        # Frozen accounts measure from the freeze point, not from today
        base = base if base and base > tenant.frozen_at else tenant.frozen_at
    elif base is None or base < now:
        base = now

    tenant.subscription_expires_at = base + timedelta(days=plan.duration_days)
    tenant.plan = plan.name
    tenant.balance = float(tenant.balance or 0) - price

    session.add(
        Payment(
            id=f"pay-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant.id,
            amount=-price,
            kind="subscription",
            status="confirmed",
            plan_name=plan.name,
            note=f"{plan.title} — {plan.duration_days} kun",
            confirmed_at=now,
            confirmed_by="tizim",
        )
    )
    # Paying reopens a business that expiry had switched off. A suspension an
    # admin applied deliberately is left alone.
    if not tenant.is_active and tenant.frozen_at is None:
        tenant.is_active = True

    await session.commit()
    return await summary(session, tenant)


async def history(session: AsyncSession, tenant_id: str, limit: int = 50) -> list:
    rows = (
        await session.execute(
            select(Payment).where(Payment.tenant_id == tenant_id)
            .order_by(desc(Payment.created_at)).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": p.id,
            "amount": p.amount,
            "kind": p.kind,
            "status": p.status,
            "note": p.note,
            "plan_name": p.plan_name,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else None,
            "confirmed_by": p.confirmed_by,
        }
        for p in rows
    ]
