"""Knowledge-base edits — what a support call most often needs to fix on a
tenant's data."""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db import repo
from app.db.base import get_session
from app.db.models import PlatformAdmin
from app.services import audit_service

router = APIRouter()


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
