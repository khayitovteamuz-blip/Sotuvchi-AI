"""
Tariff limits, and the checks that make them mean something.

The `plan` column existed for a long time while nothing read it, so every tier
bought exactly the same service. These functions are what turn a tariff into a
product: the catalog size and the monthly AI allowance a business actually gets.

A NULL limit is unlimited. Limits are read from the `plans` table on each check
rather than cached, so raising a customer's cap during a support call takes
effect on their very next request.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Message, Plan, Product, Tenant, User

logger = logging.getLogger("quota")


class QuotaExceeded(Exception):
    """Raised when an action would cross the tenant's tariff limit."""

    def __init__(self, message: str, limit: int, used: int, resource: str):
        super().__init__(message)
        self.message = message
        self.limit = limit
        self.used = used
        self.resource = resource


def _month_start() -> datetime:
    """First moment of the current month, at the business's own offset.

    Counting in UTC would end a month at 05:00 local and hand a customer five
    free hours on the wrong side of their billing period.
    """
    tz = timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))
    now = datetime.now(tz)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_plan(db: AsyncSession, tenant: Tenant) -> Optional[Plan]:
    """The tenant's tariff row, or None when the plan name has no row.

    None deliberately means "do not block": an unknown tariff is our data bug,
    and a customer's bot must not stop selling because of it.
    """
    plan = await db.get(Plan, tenant.plan)
    if plan is None:
        logger.warning(f"Tenant {tenant.id} has unknown plan '{tenant.plan}' — limits skipped")
    return plan


async def count_products(db: AsyncSession, tenant_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Product).where(Product.tenant_id == tenant_id)
        )
    ).scalar() or 0


async def count_ai_messages_this_month(db: AsyncSession, tenant_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.sender == "assistant",
                Message.created_at >= _month_start(),
            )
        )
    ).scalar() or 0


async def count_operators(db: AsyncSession, tenant_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        )
    ).scalar() or 0


async def check_products(db: AsyncSession, tenant: Tenant, adding: int = 1) -> None:
    """Raise QuotaExceeded if adding `adding` products would cross the limit."""
    plan = await get_plan(db, tenant)
    if plan is None or plan.max_products is None:
        return
    used = await count_products(db, tenant.id)
    if used + adding > plan.max_products:
        raise QuotaExceeded(
            f"'{plan.title}' tarifida {plan.max_products} tagacha mahsulot mumkin "
            f"(hozir {used} ta). Yuqoriroq tarifga o'ting yoki qo'llab-quvvatlashga murojaat qiling.",
            limit=plan.max_products,
            used=used,
            resource="products",
        )


async def check_operators(db: AsyncSession, tenant: Tenant, adding: int = 1) -> None:
    """Raise QuotaExceeded if adding a person would cross the seat limit.

    `max_operators` sat in the tariff table and on the pricing page for a long
    time without anything enforcing it — because there was no way to add a
    second person at all. It is enforced from the moment that became possible.
    """
    plan = await get_plan(db, tenant)
    if plan is None or plan.max_operators is None:
        return
    used = await count_operators(db, tenant.id)
    if used + adding > plan.max_operators:
        raise QuotaExceeded(
            f"'{plan.title}' tarifida {plan.max_operators} tagacha foydalanuvchi mumkin "
            f"(hozir {used} ta). Yuqoriroq tarifga o'ting.",
            limit=plan.max_operators,
            used=used,
            resource="operators",
        )


async def ai_allowed(db: AsyncSession, tenant: Tenant) -> bool:
    """Whether the AI may answer another message this month.

    Returns a bool instead of raising: this is checked mid-conversation with a
    real customer waiting, and the caller needs to reply politely rather than
    surface an error.
    """
    # An expired or suspended business gets no AI, however much quota is left.
    from app.services import billing_service
    await billing_service.enforce_expiry(db, tenant)
    if not tenant.is_active:
        logger.warning(f"Tenant {tenant.id} is inactive — AI withheld")
        return False

    plan = await get_plan(db, tenant)
    if plan is None or plan.max_ai_messages_monthly is None:
        return True
    used = await count_ai_messages_this_month(db, tenant.id)
    if used >= plan.max_ai_messages_monthly:
        logger.warning(
            f"Tenant {tenant.id} hit the AI quota: {used}/{plan.max_ai_messages_monthly}"
        )
        return False
    return True


async def usage(db: AsyncSession, tenant: Tenant) -> dict:
    """Everything the panels show about this tenant's consumption."""
    plan = await get_plan(db, tenant)
    products = await count_products(db, tenant.id)
    ai_messages = await count_ai_messages_this_month(db, tenant.id)
    operators = await count_operators(db, tenant.id)

    def pct(used: int, limit: Optional[int]) -> Optional[float]:
        if not limit:
            return None
        return round(used / limit * 100, 1)

    return {
        "plan": tenant.plan,
        "plan_title": plan.title if plan else tenant.plan,
        "products": {
            "used": products,
            "limit": plan.max_products if plan else None,
            "pct": pct(products, plan.max_products if plan else None),
        },
        "ai_messages": {
            "used": ai_messages,
            "limit": plan.max_ai_messages_monthly if plan else None,
            "pct": pct(ai_messages, plan.max_ai_messages_monthly if plan else None),
        },
        "operators": {
            "used": operators,
            "limit": plan.max_operators if plan else None,
            "pct": pct(operators, plan.max_operators if plan else None),
        },
    }
