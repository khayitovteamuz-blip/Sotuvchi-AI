"""Read-only order history and knowledge-base edits — the two things a
support call most often needs from a tenant's data."""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db import repo
from app.db.base import get_session
from app.db.models import Order, PlatformAdmin
from app.services import audit_service

router = APIRouter()


@router.get("/tenants/{tenant_id}/orders")
async def tenant_orders(tenant_id: str, session: AsyncSession = Depends(get_session)):
    await get_tenant_or_404(session, tenant_id)
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
    await get_tenant_or_404(session, tenant_id)
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
