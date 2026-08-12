"""
Platform API — the service operator's control panel.

Every route here reads or writes data belonging to other people's businesses, so
authorisation is attached to the router itself rather than to each endpoint: a
route added later inherits the check instead of silently shipping without one.

Login lives on a separate router because it must be reachable *before* there is
a session.
"""
import csv
import io
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import client_ip
from app.core.config import settings
from app.core.platform_auth import (
    PLATFORM_COOKIE,
    create_platform_session,
    destroy_platform_session,
    require_platform_admin,
    set_platform_cookie,
)
from app.db import repo
from app.db.base import get_session
from app.db.models import (
    Conversation,
    LoginAttempt,
    Message,
    Order,
    Payment,
    Plan,
    PlatformAdmin,
    PlatformSession,
    Product,
    Tenant,
    User,
    UserSession,
)
from app.services import audit_service, billing_service, quota_service, tenant_service
from app.services.bot_service import bot_service

logger = logging.getLogger("platform_api")

# ─── Login (no session yet, so no admin dependency) ───────────────────────────
auth_router = APIRouter(prefix="/api/platform/auth", tags=["Platform Auth"])


class PlatformLogin(BaseModel):
    email: str
    password: str


@auth_router.post("/login")
async def platform_login(
    data: PlatformLogin, request: Request, session: AsyncSession = Depends(get_session)
):
    # Same throttle table as the business panel, but a distinct key prefix so a
    # locked business login cannot lock the operator out of their own platform.
    throttle_key = f"platform|{client_ip(request)}|{data.email.strip().lower()}"
    allowed, wait = await security.check_login_allowed(session, throttle_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Juda ko'p urinish. {max(1, wait // 60)} daqiqadan keyin urinib ko'ring.",
        )

    admin = (
        await session.execute(
            select(PlatformAdmin).where(PlatformAdmin.email == data.email.strip().lower())
        )
    ).scalars().first()

    ok, needs_rehash = (False, False)
    if admin and admin.is_active:
        ok, needs_rehash = security.verify_password(data.password, admin.password_hash)

    if not ok:
        await security.record_login_failure(session, throttle_key)
        # One message for every failure mode: a distinct "no such admin" reply
        # would confirm which emails are platform accounts.
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")

    await security.record_login_success(session, throttle_key)
    if needs_rehash:
        admin.password_hash = security.hash_password(data.password)
    admin.last_login_at = func.now()
    await session.commit()

    token = await create_platform_session(session, admin.id, request)
    await audit_service.log(session, admin, "login", request=request)

    response = JSONResponse(
        content={"status": "success", "admin": {"email": admin.email, "full_name": admin.full_name}}
    )
    set_platform_cookie(response, token)
    return response


@auth_router.post("/logout")
async def platform_logout(request: Request, session: AsyncSession = Depends(get_session)):
    await destroy_platform_session(session, request)
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(PLATFORM_COOKIE)
    return response


@auth_router.get("/me")
async def platform_me(admin: PlatformAdmin = Depends(require_platform_admin)):
    return {"email": admin.email, "full_name": admin.full_name, "id": admin.id}


# ─── Everything below requires a platform admin ───────────────────────────────
router = APIRouter(
    prefix="/api/platform",
    tags=["Platform"],
    dependencies=[Depends(require_platform_admin)],
)


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


@router.get("/tenants")
async def list_tenants(session: AsyncSession = Depends(get_session)):
    """Every business, with the numbers that say whether it is healthy.

    Counts are aggregated in one grouped query per resource rather than per
    tenant — a per-tenant loop would issue N round trips to a database ~100ms
    away and make the page unusable at even fifty customers.
    """
    tenants = (await session.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()

    def grouped(rows):
        return {k: v for k, v in rows}

    products = grouped(
        (await session.execute(select(Product.tenant_id, func.count()).group_by(Product.tenant_id))).all()
    )
    orders = grouped(
        (await session.execute(select(Order.tenant_id, func.count()).group_by(Order.tenant_id))).all()
    )
    convs = grouped(
        (await session.execute(select(Conversation.tenant_id, func.count()).group_by(Conversation.tenant_id))).all()
    )
    last_seen = grouped(
        (
            await session.execute(
                select(Conversation.tenant_id, func.max(Conversation.last_message_at))
                .group_by(Conversation.tenant_id)
            )
        ).all()
    )
    ai_month = grouped(
        (
            await session.execute(
                select(Message.tenant_id, func.count())
                .where(Message.sender == "assistant", Message.created_at >= quota_service._month_start())
                .group_by(Message.tenant_id)
            )
        ).all()
    )
    owners = grouped(
        (
            await session.execute(
                select(User.tenant_id, func.min(User.email)).group_by(User.tenant_id)
            )
        ).all()
    )
    plans = {p.name: p for p in (await session.execute(select(Plan))).scalars().all()}

    out = []
    for t in tenants:
        plan = plans.get(t.plan)
        last = last_seen.get(t.id)
        out.append({
            "id": t.id,
            "business_name": t.business_name,
            "owner_email": owners.get(t.id),
            "owner_name": t.owner_name,
            "phone": t.phone,
            "plan": t.plan,
            "plan_title": plan.title if plan else t.plan,
            "is_active": t.is_active,
            "created_at": t.created_at.strftime("%Y-%m-%d") if t.created_at else None,
            "products": products.get(t.id, 0),
            "orders": orders.get(t.id, 0),
            "conversations": convs.get(t.id, 0),
            "ai_messages_month": ai_month.get(t.id, 0),
            "ai_limit": plan.max_ai_messages_monthly if plan else None,
            "product_limit": plan.max_products if plan else None,
            "balance": float(t.balance or 0),
            "sub_status": billing_service.status_of(t, plans.get(t.plan)),
            "days_left": (lambda d: round(d, 1) if d is not None else None)(billing_service.days_left(t)),
            "telegram_connected": bool(t.telegram_bot_token),
            "telegram_username": t.telegram_bot_username,
            "last_activity": last.strftime("%Y-%m-%d %H:%M") if last else None,
        })
    return out


async def _get_tenant_or_404(session: AsyncSession, tenant_id: str) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Biznes topilmadi.")
    return tenant


@router.get("/tenants/{tenant_id}")
async def tenant_detail(tenant_id: str, session: AsyncSession = Depends(get_session)):
    tenant = await _get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)
    users = (
        await session.execute(select(User).where(User.tenant_id == tenant_id))
    ).scalars().all()

    return {
        "id": tenant.id,
        "business_name": tenant.business_name,
        "plan": tenant.plan,
        "is_active": tenant.is_active,
        "created_at": tenant.created_at.strftime("%Y-%m-%d %H:%M") if tenant.created_at else None,
        "usage": await quota_service.usage(session, tenant),
        "billing": await billing_service.summary(session, tenant),
        "contact": {
            "owner_name": tenant.owner_name,
            "phone": tenant.phone,
            "telegram_contact": tenant.telegram_contact,
            "address": tenant.address,
            "contact_note": tenant.contact_note,
        },
        # Every top-up and every tariff activation, with its timestamp. The
        # question "when did this business last pay, and for what" has to be
        # answerable from the profile itself, not from a separate page.
        "payments": await billing_service.history(session, tenant_id, limit=50),
        "telegram": {
            "connected": bool(tenant.telegram_bot_token),
            "username": tenant.telegram_bot_username,
            "webhook_secret_set": bool(tenant.telegram_webhook_secret),
            "orders_group": tenant.orders_group_title,
            "work_group": tenant.work_group_title,
            "operators_group": tenant.operators_group_title,
        },
        "users": [
            {"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active}
            for u in users
        ],
        "ai": {
            "system_prompt": cfg.system_prompt,
            "ai_provider": cfg.ai_provider,
            "model_name": cfg.model_name,
            "temperature": cfg.temperature,
            "bot_enabled": cfg.bot_enabled,
            "ai_name": cfg.ai_name,
            "ai_tone": cfg.ai_tone,
            "ai_language": cfg.ai_language,
            "auto_handoff_after": cfg.auto_handoff_after,
            "greeting_message": cfg.greeting_message,
        },
        "knowledge_base": {
            "delivery_info": cfg.delivery_info,
            "delivery_fee_city": cfg.delivery_fee_city,
            "delivery_fee_regions": cfg.delivery_fee_regions,
            "payment_info": cfg.payment_info,
            "warranty_info": cfg.warranty_info,
            "return_policy": cfg.return_policy,
            "working_hours": cfg.working_hours,
            "faq": cfg.faq,
        },
    }


class TenantPatch(BaseModel):
    """Explicit field list: a free-form dict here would let a typo write any
    column on the tenant, including another business's Telegram token."""
    plan: Optional[str] = None
    is_active: Optional[bool] = None
    business_name: Optional[str] = None


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    patch: TenantPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    tenant = await _get_tenant_or_404(session, tenant_id)
    changes = {}

    if patch.plan is not None and patch.plan != tenant.plan:
        if not await session.get(Plan, patch.plan):
            raise HTTPException(status_code=400, detail=f"'{patch.plan}' tarifi mavjud emas.")
        changes["plan"] = {"from": tenant.plan, "to": patch.plan}
        tenant.plan = patch.plan

    if patch.is_active is not None and patch.is_active != tenant.is_active:
        changes["is_active"] = {"from": tenant.is_active, "to": patch.is_active}
        tenant.is_active = patch.is_active
        # Suspension stops the subscription clock instead of spending it, so a
        # business switched off for a fortnight comes back with the days it had.
        if patch.is_active:
            billing_service.unfreeze(tenant)
        else:
            billing_service.freeze(tenant)
        changes["days_left"] = round(billing_service.days_left(tenant) or 0, 1)

    if patch.business_name and patch.business_name.strip() != tenant.business_name:
        changes["business_name"] = {"from": tenant.business_name, "to": patch.business_name.strip()}
        tenant.business_name = patch.business_name.strip()

    if not changes:
        return {"status": "unchanged"}

    await session.commit()
    await audit_service.log(session, admin, "tenant_update", tenant_id, changes, request)
    return {"status": "success", "changes": changes}


class ContactPatch(BaseModel):
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    telegram_contact: Optional[str] = None
    address: Optional[str] = None
    contact_note: Optional[str] = None


@router.patch("/tenants/{tenant_id}/contact")
async def update_contact(
    tenant_id: str,
    patch: ContactPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    tenant = await _get_tenant_or_404(session, tenant_id)
    changed = []
    for field, value in patch.model_dump(exclude_unset=True).items():
        clean = (value or "").strip() or None
        if clean != getattr(tenant, field):
            setattr(tenant, field, clean)
            changed.append(field)
    if not changed:
        return {"status": "unchanged"}
    await session.commit()
    await audit_service.log(session, admin, "contact_update", tenant_id, {"fields": changed}, request)
    return {"status": "success", "changed": changed}


class AiPatch(BaseModel):
    system_prompt: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    bot_enabled: Optional[bool] = None
    auto_handoff_after: Optional[int] = None


@router.patch("/tenants/{tenant_id}/ai")
async def update_tenant_ai(
    tenant_id: str,
    patch: AiPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Fix a customer's AI configuration for them — the most common support call."""
    await _get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)

    changes = {}
    for field in ("system_prompt", "model_name", "temperature", "bot_enabled", "auto_handoff_after"):
        new = getattr(patch, field)
        if new is not None and new != getattr(cfg, field):
            old = getattr(cfg, field)
            # Prompts run to thousands of characters; the log records that it
            # changed and by how much, not a copy of the whole text.
            changes[field] = (
                {"from_len": len(old or ""), "to_len": len(new)}
                if field == "system_prompt"
                else {"from": old, "to": new}
            )
            setattr(cfg, field, new)

    if not changes:
        return {"status": "unchanged"}

    await session.commit()
    await audit_service.log(session, admin, "tenant_ai_update", tenant_id, changes, request)
    return {"status": "success", "changes": changes}


@router.post("/tenants/{tenant_id}/telegram/disconnect")
async def force_disconnect_telegram(
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Clear a stuck bot connection. The usual fix when a customer reports the
    bot has gone silent: the webhook and secret are dropped so reconnecting from
    their own panel registers a clean pair."""
    tenant = await _get_tenant_or_404(session, tenant_id)
    if tenant.telegram_bot_token:
        await bot_service.delete_webhook(tenant.telegram_bot_token)
    tenant.telegram_bot_token = None
    tenant.telegram_bot_username = None
    tenant.telegram_webhook_secret = None
    await session.commit()
    await audit_service.log(session, admin, "telegram_disconnect", tenant_id, request=request)
    return {"status": "success"}


@router.get("/tenants/{tenant_id}/conversations")
async def tenant_conversations(
    tenant_id: str, session: AsyncSession = Depends(get_session)
):
    """Read a customer's chats when they report the bot misbehaving."""
    await _get_tenant_or_404(session, tenant_id)
    return await repo.list_conversations(session, tenant_id)


@router.get("/tenants/{tenant_id}/conversations/{conv_id}")
async def tenant_conversation_detail(
    tenant_id: str, conv_id: str, session: AsyncSession = Depends(get_session)
):
    await _get_tenant_or_404(session, tenant_id)
    conv = await repo.get_conversation(session, tenant_id, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Suhbat topilmadi.")
    msgs = (
        await session.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
        )
    ).scalars().all()
    return {
        "id": conv.id,
        "customer_name": conv.customer_name,
        "status": conv.status,
        "handoff_reason": conv.handoff_reason,
        "messages": [
            {
                "sender": m.sender,
                "text": m.text,
                "model_name": m.model_name,
                "tokens": m.tokens,
                "latency_ms": m.latency_ms,
                "created_at": m.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for m in msgs
        ],
    }


# ─── Plans ────────────────────────────────────────────────────────────────────
@router.get("/plans")
async def list_plans(session: AsyncSession = Depends(get_session)):
    plans = (await session.execute(select(Plan).order_by(Plan.sort_order))).scalars().all()
    counts = {
        k: v
        for k, v in (await session.execute(select(Tenant.plan, func.count()).group_by(Tenant.plan))).all()
    }
    return [
        {
            "name": p.name,
            "title": p.title,
            "price_uzs": p.price_uzs,
            "max_products": p.max_products,
            "max_ai_messages_monthly": p.max_ai_messages_monthly,
            "max_operators": p.max_operators,
            "is_active": p.is_active,
            "tenants": counts.get(p.name, 0),
        }
        for p in plans
    ]


class PlanPatch(BaseModel):
    title: Optional[str] = None
    price_uzs: Optional[float] = None
    # null is a meaningful value here (unlimited), so the sentinel for "leave
    # alone" cannot also be null — these are only applied when present.
    max_products: Optional[int] = None
    max_ai_messages_monthly: Optional[int] = None
    max_operators: Optional[int] = None
    unlimited: Optional[list[str]] = None  # fields to explicitly clear


@router.patch("/plans/{name}")
async def update_plan(
    name: str,
    patch: PlanPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    plan = await session.get(Plan, name)
    if not plan:
        raise HTTPException(status_code=404, detail="Tarif topilmadi.")

    changes = {}
    for field in ("title", "price_uzs", "max_products", "max_ai_messages_monthly", "max_operators"):
        new = getattr(patch, field)
        if new is not None and new != getattr(plan, field):
            changes[field] = {"from": getattr(plan, field), "to": new}
            setattr(plan, field, new)

    for field in patch.unlimited or []:
        if field in ("max_products", "max_ai_messages_monthly", "max_operators"):
            if getattr(plan, field) is not None:
                changes[field] = {"from": getattr(plan, field), "to": None}
                setattr(plan, field, None)

    if not changes:
        return {"status": "unchanged"}

    await session.commit()
    await audit_service.log(session, admin, "plan_update", None, {"plan": name, **changes}, request)
    return {"status": "success", "changes": changes}


# ─── Tenant lifecycle ─────────────────────────────────────────────────────────
class TenantCreate(BaseModel):
    business_name: str
    email: str
    password: str
    plan: str = "start"


@router.post("/tenants")
async def create_tenant(
    data: TenantCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Onboard a business from the panel.

    Goes through the same registration path customers use, so a hand-created
    account gets identical defaults — a second code path here would drift and
    produce tenants that behave subtly differently.
    """
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Parol kamida 8 belgi bo'lishi kerak.")
    if data.plan and not await session.get(Plan, data.plan):
        raise HTTPException(status_code=400, detail=f"'{data.plan}' tarifi mavjud emas.")
    try:
        tenant, owner = await tenant_service.register(
            session, data.business_name, data.email, data.password
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if data.plan and data.plan != tenant.plan:
        tenant.plan = data.plan
        await session.commit()

    await audit_service.log(
        session, admin, "tenant_create", tenant.id,
        {"business_name": tenant.business_name, "email": owner.email, "plan": tenant.plan}, request,
    )
    return {"status": "success", "tenant_id": tenant.id, "email": owner.email}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    confirm: str = "",
    request: Request = None,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Erase a business and everything it owns. Irreversible.

    The caller must echo the business name back: a tenant id in a URL is easy to
    mistype, and every order, conversation and product goes with it.
    """
    tenant = await _get_tenant_or_404(session, tenant_id)
    if confirm.strip() != tenant.business_name:
        raise HTTPException(
            status_code=400,
            detail="Tasdiqlash uchun biznes nomini aynan yozing.",
        )

    snapshot = {
        "business_name": tenant.business_name,
        "plan": tenant.plan,
        "products": await quota_service.count_products(session, tenant_id),
        "orders": (
            await session.execute(
                select(func.count()).select_from(Order).where(Order.tenant_id == tenant_id)
            )
        ).scalar(),
    }
    if tenant.telegram_bot_token:
        await bot_service.delete_webhook(tenant.telegram_bot_token)

    # Every child table carries ondelete=CASCADE, so one statement clears the
    # whole graph. The audit row is written first so the record survives even if
    # the delete is the last thing this admin ever does.
    await audit_service.log(session, admin, "tenant_delete", tenant_id, snapshot, request)
    await session.execute(sa_delete(Tenant).where(Tenant.id == tenant_id))
    await session.commit()
    return {"status": "success", "deleted": snapshot}


# ─── Users inside a tenant ────────────────────────────────────────────────────
@router.post("/tenants/{tenant_id}/users/{user_id}/reset-password")
async def reset_user_password(
    tenant_id: str,
    user_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Issue a new password and return it once.

    The most common support call there is. The generated value is shown to the
    admin a single time and never stored in readable form — only its argon2
    hash goes to the database.
    """
    await _get_tenant_or_404(session, tenant_id)
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")

    new_password = secrets.token_urlsafe(9)
    user.password_hash = security.hash_password(new_password)
    await session.commit()

    # Old sessions must die with the old password, or a stolen cookie survives
    # the very reset that was meant to cut it off.
    await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
    await session.execute(
        sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{user.email}"))
    )
    await session.commit()

    await audit_service.log(
        session, admin, "user_password_reset", tenant_id, {"email": user.email}, request
    )
    return {"status": "success", "email": user.email, "password": new_password}


class UserPatch(BaseModel):
    is_active: Optional[bool] = None


@router.patch("/tenants/{tenant_id}/users/{user_id}")
async def update_user(
    tenant_id: str,
    user_id: str,
    patch: UserPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    await _get_tenant_or_404(session, tenant_id)
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")

    if patch.is_active is None or patch.is_active == user.is_active:
        return {"status": "unchanged"}

    changes = {"email": user.email, "is_active": {"from": user.is_active, "to": patch.is_active}}
    user.is_active = patch.is_active
    await session.commit()
    if not patch.is_active:
        await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
        await session.commit()
    await audit_service.log(session, admin, "user_update", tenant_id, changes, request)
    return {"status": "success", "changes": changes}


@router.post("/tenants/{tenant_id}/unlock")
async def unlock_tenant_logins(
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Clear the login throttle for everyone in this business.

    Someone who mistyped their password eight times is locked out for fifteen
    minutes; without this the only answer support can give them is "wait".
    """
    await _get_tenant_or_404(session, tenant_id)
    emails = (
        await session.execute(select(User.email).where(User.tenant_id == tenant_id))
    ).scalars().all()
    for email in emails:
        await session.execute(sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{email}")))
    await session.commit()
    await audit_service.log(session, admin, "login_unlock", tenant_id, {"users": len(emails)}, request)
    return {"status": "success", "users": len(emails)}


@router.post("/tenants/{tenant_id}/logout-all")
async def logout_all(
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """End every browser session this business has open — the containment step
    when an owner reports their account may be compromised."""
    await _get_tenant_or_404(session, tenant_id)
    ids = (
        await session.execute(select(User.id).where(User.tenant_id == tenant_id))
    ).scalars().all()
    res = await session.execute(sa_delete(UserSession).where(UserSession.user_id.in_(ids)))
    await session.commit()
    await audit_service.log(session, admin, "sessions_revoked", tenant_id, {"count": res.rowcount}, request)
    return {"status": "success", "revoked": res.rowcount or 0}


# ─── Support views ────────────────────────────────────────────────────────────
@router.get("/tenants/{tenant_id}/orders")
async def tenant_orders(tenant_id: str, session: AsyncSession = Depends(get_session)):
    await _get_tenant_or_404(session, tenant_id)
    rows = (
        await session.execute(
            select(Order).where(Order.tenant_id == tenant_id)
            .order_by(Order.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": o.id,
            "customer_name": o.customer_name,
            "customer_phone": o.customer_phone,
            "total_amount": o.total_amount,
            "status": o.status,
            "from_ai": bool(o.conversation_id),
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else None,
        }
        for o in rows
    ]


class KbPatch(BaseModel):
    delivery_info: Optional[str] = None
    delivery_fee_city: Optional[float] = None
    delivery_fee_regions: Optional[float] = None
    payment_info: Optional[str] = None
    warranty_info: Optional[str] = None
    return_policy: Optional[str] = None
    working_hours: Optional[str] = None
    faq: Optional[str] = None


@router.patch("/tenants/{tenant_id}/kb")
async def update_kb(
    tenant_id: str,
    patch: KbPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Fill in a customer's knowledge base for them.

    An empty one is why the AI escalates every delivery and warranty question,
    and it is faster to fix it on the call than to talk someone through it.
    """
    await _get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)
    changed = []
    for field, value in patch.model_dump(exclude_unset=True).items():
        if value is not None and value != getattr(cfg, field):
            setattr(cfg, field, value)
            changed.append(field)
    if not changed:
        return {"status": "unchanged"}
    await session.commit()
    await audit_service.log(session, admin, "kb_update", tenant_id, {"fields": changed}, request)
    return {"status": "success", "changed": changed}


# ─── Platform admins ──────────────────────────────────────────────────────────
@router.get("/admins")
async def list_admins(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(PlatformAdmin).order_by(PlatformAdmin.created_at))
    ).scalars().all()
    return [
        {
            "id": a.id,
            "email": a.email,
            "full_name": a.full_name,
            "is_active": a.is_active,
            "created_at": a.created_at.strftime("%Y-%m-%d") if a.created_at else None,
            "last_login_at": a.last_login_at.strftime("%Y-%m-%d %H:%M") if a.last_login_at else None,
        }
        for a in rows
    ]


class AdminCreate(BaseModel):
    email: str
    full_name: Optional[str] = None
    password: str


@router.post("/admins")
async def create_admin(
    data: AdminCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Only an existing admin can mint another one — the shell script stays the
    way in for the very first account."""
    if len(data.password) < 10:
        raise HTTPException(status_code=400, detail="Parol kamida 10 belgi bo'lishi kerak.")
    email = data.email.strip().lower()
    exists = (
        await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="Bu email allaqachon ro'yxatdan o'tgan.")

    session.add(
        PlatformAdmin(
            id=f"padmin-{uuid.uuid4().hex[:12]}",
            email=email,
            full_name=(data.full_name or "").strip() or None,
            password_hash=security.hash_password(data.password),
        )
    )
    await session.commit()
    await audit_service.log(session, admin, "admin_create", None, {"email": email}, request)
    return {"status": "success", "email": email}


class AdminPatch(BaseModel):
    is_active: Optional[bool] = None


@router.patch("/admins/{admin_id}")
async def update_admin(
    admin_id: str,
    patch: AdminPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    target = await session.get(PlatformAdmin, admin_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin topilmadi.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="O'z hisobingizni o'chira olmaysiz.")
    if patch.is_active is None or patch.is_active == target.is_active:
        return {"status": "unchanged"}

    # Guard against locking everyone out of the platform panel
    if not patch.is_active:
        active = (
            await session.execute(
                select(func.count()).select_from(PlatformAdmin)
                .where(PlatformAdmin.is_active.is_(True))
            )
        ).scalar() or 0
        if active <= 1:
            raise HTTPException(status_code=400, detail="Oxirgi faol adminni o'chirib bo'lmaydi.")

    target.is_active = patch.is_active
    await session.commit()
    if not patch.is_active:
        await session.execute(sa_delete(PlatformSession).where(PlatformSession.admin_id == admin_id))
        await session.commit()
    await audit_service.log(
        session, admin, "admin_update", None, {"email": target.email, "is_active": patch.is_active}, request
    )
    return {"status": "success"}


# ─── Billing ──────────────────────────────────────────────────────────────────
@router.get("/payments")
async def list_payments(
    status: str = "pending",
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    """Top-up claims awaiting a decision, newest first."""
    q = (
        select(Payment, Tenant.business_name)
        .join(Tenant, Tenant.id == Payment.tenant_id)
        .order_by(Payment.created_at.desc())
        .limit(min(limit, 500))
    )
    if status != "all":
        q = q.where(Payment.status == status)

    return [
        {
            "id": p.id,
            "tenant_id": p.tenant_id,
            "business_name": name,
            "amount": p.amount,
            "kind": p.kind,
            "status": p.status,
            "note": p.note,
            "plan_name": p.plan_name,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else None,
            "confirmed_by": p.confirmed_by,
        }
        for p, name in (await session.execute(q)).all()
    ]


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(
    payment_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Money only becomes balance here. A business filing a claim cannot credit
    itself — an admin has to say the transfer actually arrived."""
    payment = await session.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi.")
    tenant = await _get_tenant_or_404(session, payment.tenant_id)
    try:
        await billing_service.confirm_topup(session, payment, tenant, admin.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit_service.log(
        session, admin, "payment_confirm", tenant.id,
        {"amount": payment.amount, "balance": tenant.balance}, request,
    )
    return {"status": "success", "balance": tenant.balance}


@router.post("/payments/{payment_id}/reject")
async def reject_payment(
    payment_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    payment = await session.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi.")
    try:
        await billing_service.reject_topup(session, payment, admin.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit_service.log(
        session, admin, "payment_reject", payment.tenant_id, {"amount": payment.amount}, request
    )
    return {"status": "success"}


class BalanceAdjust(BaseModel):
    amount: float
    note: str = ""


@router.post("/tenants/{tenant_id}/balance")
async def adjust_tenant_balance(
    tenant_id: str,
    data: BalanceAdjust,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Manual correction — a refund, a goodwill credit, a bank fee."""
    tenant = await _get_tenant_or_404(session, tenant_id)
    if data.amount == 0:
        raise HTTPException(status_code=400, detail="Summa nol bo'lmasligi kerak.")
    if not data.note.strip():
        raise HTTPException(status_code=400, detail="Sabab yozilishi shart.")
    await billing_service.adjust_balance(session, tenant, data.amount, admin.email, data.note)
    await audit_service.log(
        session, admin, "balance_adjust", tenant_id,
        {"amount": data.amount, "note": data.note, "balance": tenant.balance}, request,
    )
    return {"status": "success", "balance": tenant.balance}


@router.get("/tenants/{tenant_id}/payments")
async def tenant_payments(tenant_id: str, session: AsyncSession = Depends(get_session)):
    await _get_tenant_or_404(session, tenant_id)
    return await billing_service.history(session, tenant_id)


# ─── Export ───────────────────────────────────────────────────────────────────
@router.get("/export/tenants.csv")
async def export_tenants(session: AsyncSession = Depends(get_session)):
    rows = await list_tenants(session)
    cols = ["business_name", "owner_email", "plan_title", "is_active", "created_at",
            "products", "orders", "conversations", "ai_messages_month",
            "telegram_username", "last_activity"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return Response(
        # BOM so Excel opens Uzbek text correctly
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bizneslar.csv"'},
    )


# ─── Audit ────────────────────────────────────────────────────────────────────
@router.get("/audit")
async def audit_log(
    tenant_id: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    return await audit_service.recent(session, limit=min(limit, 500), tenant_id=tenant_id)
