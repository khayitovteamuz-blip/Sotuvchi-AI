"""
Admin API — all endpoints are tenant-scoped via the current user's tenant_id.
Data lives in Postgres (see app/db/repo.py).
"""
import uuid
from typing import List

from fastapi import APIRouter, Body, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth
from app.core.config import BASE_DIR
from app.db import repo
from app.db.base import get_session
from app.db.models import User
from app.models.schema import Category, DashboardStats, Order, Product, SystemSettings
from app.services import categorize_service, import_service, tenant_service
from app.services.sheets_service import sheets_service

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ─── Dashboard ────────────────────────────────────────────────────────────────
@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    s = await repo.dashboard_stats(session, user.tenant_id)
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
    return await repo.create_product(session, user.tenant_id, product.model_dump())


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


@router.put("/orders/{order_id}/status", response_model=Order)
async def update_order_status(order_id: str, status: str = Body(..., embed=True), user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
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


@router.post("/upload")
async def upload_image(file: UploadFile = File(...), user: User = Depends(require_auth)):
    try:
        ext = file.filename.split(".")[-1] if "." in file.filename else "png"
        filename = f"img_{uuid.uuid4().hex[:10]}.{ext}"
        filepath = UPLOADS_DIR / filename
        contents = await file.read()
        with open(filepath, "wb") as f:
            f.write(contents)
        return {"status": "success", "image_url": f"/static/uploads/{filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rasm yuklashda xatolik: {str(e)}")


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

    try:
        return await import_service.import_products(
            session, user.tenant_id, file.filename or "", content, dry_run=dry_run
        )
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
async def get_analytics(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.analytics(session, user.tenant_id)


@router.get("/customers")
async def get_customers(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.list_customers(session, user.tenant_id)


# ─── Integrations ─────────────────────────────────────────────────────────────
@router.get("/integrations/status")
async def get_integrations_status(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    s = await repo.get_settings(session, user.tenant_id)
    return {
        "google_sheets": sheets_service.is_connected(),
        "telegram_bot": bool(tenant and tenant.telegram_bot_token),
        "telegram_bot_username": tenant.telegram_bot_username if tenant else None,
        "ai_provider": s.ai_provider,
    }
