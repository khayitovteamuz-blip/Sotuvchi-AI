"""Tariffs — limits, price, and the AI model tier they buy."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platform_auth import require_platform_admin
from app.db.base import get_session
from app.db.models import Plan, PlatformAdmin, Tenant
from app.services import ai_models, audit_service

router = APIRouter()


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
            "max_model_tier": p.max_model_tier,
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
    max_model_tier: Optional[str] = None  # lite | flash | pro — see ai_models.TIER_ORDER
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

    if patch.max_model_tier is not None and patch.max_model_tier not in ai_models.TIER_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"max_model_tier {ai_models.TIER_ORDER} dan biri bo'lishi kerak.",
        )

    changes = {}
    for field in ("title", "price_uzs", "max_products", "max_ai_messages_monthly",
                  "max_operators", "max_model_tier"):
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
