"""Top-up claims, manual balance corrections, and subscription extensions —
the money side of a tenant's account."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db.base import get_session
from app.db.models import Payment, PlatformAdmin, Tenant
from app.services import audit_service, billing_service

router = APIRouter()


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
    tenant = await get_tenant_or_404(session, payment.tenant_id)
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
    tenant = await get_tenant_or_404(session, tenant_id)
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


class ExtendPatch(BaseModel):
    days: int
    note: str = ""


@router.post("/tenants/{tenant_id}/extend")
async def extend_subscription(
    tenant_id: str,
    patch: ExtendPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Add days to a subscription by hand.

    Support needs this constantly — goodwill after an outage, a deal closed
    offline, a transfer that arrived late. Flipping `is_active` back on did not
    work: the very next request re-evaluated the expired date and switched the
    business off again.
    """
    if not 1 <= patch.days <= 365:
        raise HTTPException(status_code=400, detail="Kun soni 1 dan 365 gacha bo'lsin.")
    tenant = await get_tenant_or_404(session, tenant_id)
    await billing_service.extend(session, tenant, patch.days, patch.note, admin.email)
    await audit_service.log(
        session, admin, "subscription_extend", tenant_id,
        {"days": patch.days, "note": patch.note}, request,
    )
    return await billing_service.summary(session, tenant)


@router.get("/tenants/{tenant_id}/payments")
async def tenant_payments(tenant_id: str, session: AsyncSession = Depends(get_session)):
    await get_tenant_or_404(session, tenant_id)
    return await billing_service.history(session, tenant_id)
