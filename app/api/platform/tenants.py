"""Tenant CRUD, contact info, Telegram connection, conversation read access,
and lifecycle (create/delete) — the core of a business's platform profile."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db import repo
from app.db.base import get_session
from app.db.models import (
    Conversation,
    Message,
    Order,
    PlatformAdmin,
    Plan,
    Product,
    Tenant,
    User,
)
from app.services import audit_service, billing_service, quota_service, tenant_service
from app.services.bot_service import bot_service

router = APIRouter()


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
            "logo_url": t.logo_url,
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


@router.get("/tenants/{tenant_id}")
async def tenant_detail(tenant_id: str, session: AsyncSession = Depends(get_session)):
    tenant = await get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)
    users = (
        await session.execute(select(User).where(User.tenant_id == tenant_id))
    ).scalars().all()

    return {
        "id": tenant.id,
        "business_name": tenant.business_name,
        "logo_url": tenant.logo_url,
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
    tenant = await get_tenant_or_404(session, tenant_id)
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
    tenant = await get_tenant_or_404(session, tenant_id)
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
    tenant = await get_tenant_or_404(session, tenant_id)
    if tenant.telegram_bot_token:
        await bot_service.delete_webhook(tenant.telegram_bot_token)
    tenant.telegram_bot_token = None
    tenant.telegram_bot_username = None
    tenant.telegram_webhook_secret = None
    await session.commit()
    await audit_service.log(session, admin, "telegram_disconnect", tenant_id, request=request)
    return {"status": "success"}


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
    tenant = await get_tenant_or_404(session, tenant_id)
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
