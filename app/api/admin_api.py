"""
Admin API — all endpoints are tenant-scoped via the current user's tenant_id.
Data lives in Postgres (see app/db/repo.py).
"""
from typing import List

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import periods
from app.core.auth import (require_auth, require_auth_unpaid_ok,
                           require_owner_unpaid_ok)
from app.core.config import BASE_DIR
from app.db import repo
from app.db.base import get_session
from app.db.models import Plan, User
from app.models.schema import Category, DashboardStats, Order, Product, SystemSettings
from app.services import (billing_service, categorize_service, import_service,
                          quota_service, storage_service, tenant_service)
from app.services.sheets_service import sheets_service

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ─── Dashboard ────────────────────────────────────────────────────────────────
@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    period: str = Query(periods.DEFAULT_PERIOD, description="today | week | month | all"),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    s = await repo.dashboard_stats(session, user.tenant_id, period)
    return DashboardStats(**s)


# ─── Categories ───────────────────────────────────────────────────────────────
@router.get("/categories", response_model=List[Category])
async def get_categories(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.list_categories(session, user.tenant_id)


@router.post("/categories", response_model=Category)
async def create_category(category: Category, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.create_category(session, user.tenant_id, category.model_dump())


@router.put("/categories/{category_id}", response_model=Category)
async def update_category(category_id: str, category: Category, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    updated = await repo.update_category(session, user.tenant_id, category_id, category.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")
    return updated


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    if not await repo.delete_category(session, user.tenant_id, category_id):
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")
    return {"status": "success", "message": "Kategoriya o'chirildi."}


# ─── Products ─────────────────────────────────────────────────────────────────
@router.get("/products", response_model=List[Product])
async def list_products(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.list_products(session, user.tenant_id)


@router.post("/products", response_model=Product)
async def create_product(product: Product, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    try:
        await quota_service.check_products(session, tenant, adding=1)
    except quota_service.QuotaExceeded as e:
        # 402: the fix is a tariff change, not a corrected request
        raise HTTPException(status_code=402, detail=e.message)
    return await repo.create_product(session, user.tenant_id, product.model_dump())


@router.get("/usage")
async def get_usage(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    """What the business has consumed against its tariff."""
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    return await quota_service.usage(session, tenant)


# ─── Billing (the business's own account) ─────────────────────────────────────
@router.get("/billing")
async def get_billing(user: User = Depends(require_auth_unpaid_ok), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    plans = (
        await session.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)
        )
    ).scalars().all()
    return {
        **await billing_service.summary(session, tenant),
        "plans": [
            {
                "name": p.name,
                "title": p.title,
                "price_uzs": p.price_uzs,
                "duration_days": p.duration_days,
                "max_products": p.max_products,
                "max_ai_messages_monthly": p.max_ai_messages_monthly,
                "max_operators": p.max_operators,
                "current": p.name == tenant.plan,
            }
            for p in plans
        ],
        "history": await billing_service.history(session, user.tenant_id, limit=20),
    }


@router.post("/billing/topup")
async def request_topup(
    amount: float = Body(..., embed=True),
    note: str = Body("", embed=True),
    user: User = Depends(require_owner_unpaid_ok),
    session: AsyncSession = Depends(get_session),
):
    """File a transfer claim. It sits pending until an operator confirms the
    money arrived — a business cannot credit its own balance."""
    try:
        payment = await billing_service.request_topup(session, user.tenant_id, amount, note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "pending",
        "id": payment.id,
        "message": "So'rov yuborildi. To'lov tasdiqlangach hisobingizga tushadi.",
    }


@router.post("/billing/auto-renew")
async def set_auto_renew(
    enabled: bool = Body(..., embed=True),
    user: User = Depends(require_owner_unpaid_ok),
    session: AsyncSession = Depends(get_session),
):
    """Renew from the balance on the day the period ends, or don't."""
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    tenant.auto_renew = bool(enabled)
    await session.commit()
    return {"status": "success", "auto_renew": tenant.auto_renew}


@router.post("/billing/subscribe")
async def subscribe(
    plan: str = Body(..., embed=True),
    user: User = Depends(require_owner_unpaid_ok),
    session: AsyncSession = Depends(get_session),
):
    """Buy or renew a tariff from the balance."""
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    target = await session.get(Plan, plan)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="Bunday tarif yo'q.")
    try:
        return await billing_service.buy_plan(session, tenant, target)
    except ValueError as e:
        # 402: the fix is money, not a corrected request
        raise HTTPException(status_code=402, detail=str(e))


@router.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, product: Product, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    updated = await repo.update_product(session, user.tenant_id, product_id, product.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")
    return updated


@router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    if not await repo.delete_product(session, user.tenant_id, product_id):
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")
    return {"status": "success", "message": "Mahsulot o'chirildi."}


# ─── Orders ───────────────────────────────────────────────────────────────────
@router.get("/orders", response_model=List[Order])
async def list_orders(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.list_orders(session, user.tenant_id)


# The panel filters and colours orders by these exact strings. Anything else
# saved here would vanish from every filter — visible in no tab, counted in no
# total — so an unknown status is refused rather than stored.
ORDER_STATUSES = ("Yangi", "Tasdiqlandi", "Yo'lda", "Yetkazildi", "Bekor qilindi")


@router.put("/orders/{order_id}/status", response_model=Order)
async def update_order_status(order_id: str, status: str = Body(..., embed=True), user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    if status not in ORDER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Noma'lum holat. Ruxsat etilganlari: {', '.join(ORDER_STATUSES)}.",
        )
    updated = await repo.update_order_status(session, user.tenant_id, order_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    return updated


# ─── Settings ─────────────────────────────────────────────────────────────────
@router.get("/settings", response_model=SystemSettings)
async def get_settings(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.get_settings(session, user.tenant_id)


@router.post("/settings", response_model=SystemSettings)
async def save_settings(settings_data: SystemSettings, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.save_settings(session, user.tenant_id, settings_data.model_dump())


# ─── Image Upload ─────────────────────────────────────────────────────────────
UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# The extension comes from the file's own bytes, never from the uploaded
# filename: a name like "x.png/../../app/main" would otherwise write outside
# the uploads folder, and an .svg or .html would be served from our own origin
# — stored XSS against a shop owner who is logged in.
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # matches the "max 5MB" the panel promises


@router.post("/upload")
async def upload_image(file: UploadFile = File(...), user: User = Depends(require_auth)):
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Faqat JPG, PNG, WEBP yoki GIF rasm yuklash mumkin.",
        )

    contents = await file.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Rasm hajmi 5 MB dan oshmasin.")
    if not contents:
        raise HTTPException(status_code=400, detail="Fayl bo'sh.")

    actual, ext = storage_service.sniff(contents)
    if actual != declared:
        raise HTTPException(
            status_code=400,
            detail="Fayl rasm emas yoki turi mos kelmadi.",
        )

    try:
        url = storage_service.save_image(user.tenant_id, contents, ext, actual)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Rasmni saqlab bo'lmadi: {e}")

    return {"status": "success", "image_url": url}


@router.get("/storage")
async def storage_status(user: User = Depends(require_auth)):
    """Whether uploaded pictures actually survive a deploy."""
    return storage_service.status()


# ─── Catalog import (Excel / CSV) ─────────────────────────────────────────────
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/products/import")
async def import_products(
    file: UploadFile = File(...),
    dry_run: bool = False,
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Bulk-load a catalog from the price list the business already keeps."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Fayl bo'sh.")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="Fayl 10 MB dan katta.")

    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    try:
        # Parse once as a dry run to learn how many rows are new, check the
        # tariff against that, and only then write. Checking after the import
        # would leave the rows in place and turn the limit into a suggestion.
        preview = await import_service.import_products(
            session, user.tenant_id, file.filename or "", content, dry_run=True
        )
        if preview.get("success") and preview.get("added"):
            try:
                await quota_service.check_products(session, tenant, adding=preview["added"])
            except quota_service.QuotaExceeded as e:
                raise HTTPException(status_code=402, detail=e.message)

        if dry_run:
            return preview
        return await import_service.import_products(
            session, user.tenant_id, file.filename or "", content, dry_run=False
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Import xatosi: {e}")


@router.post("/products/auto-categorize")
async def auto_categorize(
    only_uncategorized: bool = True,
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Let the AI group the catalog — an imported price list has no categories."""
    return await categorize_service.auto_categorize(
        session, user.tenant_id, only_uncategorized=only_uncategorized
    )


@router.get("/products/import-template")
async def import_template(user: User = Depends(require_auth)):
    """Download a correctly-shaped starter file."""
    csv_text = import_service.build_template_csv()
    return Response(
        content=csv_text.encode("utf-8-sig"),  # BOM so Excel shows Cyrillic/Uzbek correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sotuvchi-katalog-namuna.csv"'},
    )


# ─── Analytics & Customers ────────────────────────────────────────────────────
@router.get("/analytics")
async def get_analytics(
    period: str = Query(periods.DEFAULT_PERIOD, description="today | week | month | all"),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    return await repo.analytics(session, user.tenant_id, period)


@router.get("/customers")
async def get_customers(
    q: str = Query("", description="Ism yoki telefon bo'yicha qidiruv"),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    return await repo.list_customers(session, user.tenant_id, q=q)


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: str,
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """One customer with every order and chat they have ever had here."""
    detail = await repo.customer_detail(session, user.tenant_id, customer_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    return detail


@router.put("/customers/{customer_id}/note")
async def set_customer_note(
    customer_id: str,
    note: str = Body("", embed=True),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """What the shop knows that the system does not — "prefers evening delivery"."""
    if not await repo.set_customer_note(session, user.tenant_id, customer_id, note):
        raise HTTPException(status_code=404, detail="Mijoz topilmadi.")
    return {"status": "success"}


# ─── Integrations ─────────────────────────────────────────────────────────────
@router.get("/integrations/status")
async def get_integrations_status(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    s = await repo.get_settings(session, user.tenant_id)
    sheets = sheets_service.status()
    return {
        "google_sheets": sheets["connected"],
        "google_sheets_reason": sheets["reason"],
        "telegram_bot": bool(tenant and tenant.telegram_bot_token),
        "telegram_bot_username": tenant.telegram_bot_username if tenant else None,
        "ai_provider": s.ai_provider,
    }
