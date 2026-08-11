"""
Platform API — the service operator's control panel.

Every route here reads or writes data belonging to other people's businesses, so
authorisation is attached to the router itself rather than to each endpoint: a
route added later inherits the check instead of silently shipping without one.

Login lives on a separate router because it must be reachable *before* there is
a session.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import client_ip
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
    Message,
    Order,
    Plan,
    PlatformAdmin,
    Product,
    Tenant,
    User,
)
from app.services import audit_service, quota_service
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

    return {
        "tenants": tenants,
        "tenants_active": active,
        "orders": orders or 0,
        "revenue": float(revenue or 0),
        "conversations": convs,
        "tokens": int(tokens or 0),
        "prompt_tokens": int(prompt_t or 0),
        "output_tokens": int(out_t or 0),
        "cost": repo._cost(int(prompt_t or 0), int(out_t or 0), int(tokens or 0)),
        "by_plan": by_plan,
    }


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

    if patch.business_name and patch.business_name.strip() != tenant.business_name:
        changes["business_name"] = {"from": tenant.business_name, "to": patch.business_name.strip()}
        tenant.business_name = patch.business_name.strip()

    if not changes:
        return {"status": "unchanged"}

    await session.commit()
    await audit_service.log(session, admin, "tenant_update", tenant_id, changes, request)
    return {"status": "success", "changes": changes}


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


# ─── Audit ────────────────────────────────────────────────────────────────────
@router.get("/audit")
async def audit_log(
    tenant_id: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    return await audit_service.recent(session, limit=min(limit, 500), tenant_id=tenant_id)
