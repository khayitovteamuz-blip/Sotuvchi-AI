"""Platform-wide stats and activity series — the operator's own dashboard."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import repo
from app.db.base import get_session
from app.db.models import Conversation, Message, Order, Payment, Tenant

router = APIRouter()


@router.get("/stats")
async def platform_stats(session: AsyncSession = Depends(get_session)):
    """Service-wide totals — the operator's own dashboard."""
    tenants = (await session.execute(select(func.count()).select_from(Tenant))).scalar() or 0
    active = (
        await session.execute(
            select(func.count()).select_from(Tenant).where(Tenant.is_active.is_(True))
        )
    ).scalar() or 0
    orders, revenue = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        )
    ).first()
    convs = (await session.execute(select(func.count()).select_from(Conversation))).scalar() or 0
    tokens, prompt_t, out_t = (
        await session.execute(
            select(
                func.coalesce(func.sum(Message.tokens), 0),
                func.coalesce(func.sum(Message.prompt_tokens), 0),
                func.coalesce(func.sum(Message.output_tokens), 0),
            ).where(Message.sender == "assistant")
        )
    ).first()

    by_plan = {
        name: n
        for name, n in (
            await session.execute(select(Tenant.plan, func.count()).group_by(Tenant.plan))
        ).all()
    }

    # The platform's own money. Orders belong to the shops' customers and are
    # none of our income — treating that sum as revenue overstated it by orders
    # of magnitude and told the operator nothing about their own business.
    cash_in, subs_sold, held = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(Payment.amount).filter(
                        (Payment.kind == "topup") & (Payment.status == "confirmed")
                    ), 0,
                ),
                func.coalesce(
                    func.sum(-Payment.amount).filter(Payment.kind == "subscription"), 0
                ),
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.status == "pending"), 0
                ),
            )
        )
    ).first()

    balances = (
        await session.execute(select(func.coalesce(func.sum(Tenant.balance), 0)))
    ).scalar()

    return {
        "tenants": tenants,
        "tenants_active": active,
        "orders": orders or 0,
        # Platform income: money businesses actually transferred to us
        "cash_in": float(cash_in or 0),
        "subscriptions_sold": float(subs_sold or 0),
        # Balance sitting on accounts — received but not yet earned
        "balance_held": float(balances or 0),
        "pending_topups": float(held or 0),
        # The shops' own trade. Kept as context, never as our revenue.
        "shops_turnover": float(revenue or 0),
        "conversations": convs,
        "tokens": int(tokens or 0),
        "prompt_tokens": int(prompt_t or 0),
        "output_tokens": int(out_t or 0),
        "cost": repo._cost(int(prompt_t or 0), int(out_t or 0), int(tokens or 0)),
        "by_plan": by_plan,
    }


# Bucket sizes: enough points to see a shape, few enough to stay readable.
GRAIN = {"day": 30, "month": 12, "year": 5}
_MONTHS = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn",
           "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]


def _bucket_starts(grain: str, count: int, tz: timezone) -> list:
    """Period starts, oldest first, in the business's own time zone."""
    now = datetime.now(tz)
    if grain == "day":
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [today - timedelta(days=i) for i in range(count - 1, -1, -1)]
    if grain == "year":
        return [
            datetime(now.year - i, 1, 1, tzinfo=tz) for i in range(count - 1, -1, -1)
        ]
    out, y, m = [], now.year, now.month
    for _ in range(count):
        out.append(datetime(y, m, 1, tzinfo=tz))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _label(grain: str, d: datetime) -> str:
    if grain == "day":
        return f"{d.day} {_MONTHS[d.month - 1]}"
    if grain == "year":
        return str(d.year)
    return _MONTHS[d.month - 1]


@router.get("/series")
async def platform_series(
    grain: str = "month",
    session: AsyncSession = Depends(get_session),
):
    """Activity across the whole service, oldest first.

    Empty periods still appear with zeros: a chart that drops them compresses
    the gaps and makes a quiet stretch look like steady trade.
    """
    grain = grain if grain in GRAIN else "month"
    starts = _bucket_starts(grain, GRAIN[grain], timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS)))
    start = starts[0]

    # date_trunc on a timestamptz truncates in the session time zone, which is
    # UTC here. Shifting the column by the offset first makes the truncation
    # land on local boundaries — otherwise the first five hours of every period
    # are counted against the previous one.
    shift = literal_column(f"interval '{int(settings.TIMEZONE_OFFSET_HOURS)} hours'")

    def bucketed(rows):
        return {r[0].date(): r[1:] for r in rows}

    o_at = func.date_trunc(grain, Order.created_at + shift)
    orders = bucketed(
        (
            await session.execute(
                select(o_at, func.count(), func.coalesce(func.sum(Order.total_amount), 0))
                .where(Order.created_at >= start)
                .group_by(o_at)
            )
        ).all()
    )

    c_at = func.date_trunc(grain, Conversation.created_at + shift)
    convs = bucketed(
        (
            await session.execute(
                select(c_at, func.count())
                .where(Conversation.created_at >= start)
                .group_by(c_at)
            )
        ).all()
    )

    # The platform's own income, so the chart can show the same figure the hero
    # card leads with rather than only the shops' activity.
    p_at = func.date_trunc(grain, Payment.created_at + shift)
    income = bucketed(
        (
            await session.execute(
                select(p_at, func.coalesce(func.sum(Payment.amount), 0))
                .where(
                    Payment.created_at >= start,
                    Payment.kind == "topup",
                    Payment.status == "confirmed",
                )
                .group_by(p_at)
            )
        ).all()
    )

    now_key = starts[-1].date()
    return [
        {
            "label": _label(grain, d),
            "year": d.year,
            "orders": (orders.get(d.date()) or (0, 0))[0],
            "revenue": float((orders.get(d.date()) or (0, 0))[1]),
            "conversations": (convs.get(d.date()) or (0,))[0],
            "income": float((income.get(d.date()) or (0,))[0]),
            "current": d.date() == now_key,
        }
        for d in starts
    ]
