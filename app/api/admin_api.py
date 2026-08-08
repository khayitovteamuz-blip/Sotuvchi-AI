from typing import List
from fastapi import APIRouter, HTTPException, Body, Depends
from app.models.schema import Product, Order, SystemSettings, DashboardStats, Category
from app.core.auth import require_auth
from app.core.tenant_manager import tenant_manager
from app.core.config import BASE_DIR
from app.services.sheets_service import sheets_service
from app.services.bot_service import bot_service

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def get_db(tenant=Depends(require_auth)):
    """Helper dependency: returns the DB instance for the current tenant."""
    return tenant_manager.get_tenant_db(tenant.id)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(db=Depends(get_db)):
    orders = db.get_orders()
    total_revenue = sum(o.total_amount for o in orders if o.status != "Bekor qilindi")
    total_orders = len(orders)
    active_leads = len(db.chat_history)
    conversion_rate = (total_orders / active_leads * 100) if active_leads > 0 else 0.0

    weekly_labels = ["Dush", "Sesh", "Chor", "Pays", "Juma", "Shan", "Yak"]
    weekly_sales = [2500000.0, 4100000.0, 3200000.0, 5600000.0, 4800000.0, 7100000.0,
                    max(total_revenue, 15200000.0)]

    return DashboardStats(
        total_revenue=total_revenue,
        total_orders=total_orders,
        active_leads=active_leads,
        conversion_rate=round(conversion_rate, 1),
        recent_orders=orders[:5],
        weekly_sales=weekly_sales,
        weekly_labels=weekly_labels
    )


# ─── Categories ──────────────────────────────────────────────────────────────
@router.get("/categories", response_model=List[Category])
async def get_categories(db=Depends(get_db)):
    return db.get_categories()


@router.post("/categories", response_model=Category)
async def create_category(category: Category, db=Depends(get_db)):
    return db.add_category(category)


@router.put("/categories/{category_id}", response_model=Category)
async def update_category(category_id: str, category: Category, db=Depends(get_db)):
    updated = db.update_category(category_id, category)
    if not updated:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")
    return updated


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, db=Depends(get_db)):
    success = db.delete_category(category_id)
    if not success:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")
    return {"status": "success", "message": "Kategoriya o'chirildi."}


# ─── Products ────────────────────────────────────────────────────────────────
@router.get("/products", response_model=List[Product])
async def list_products(db=Depends(get_db)):
    return db.get_products()


@router.post("/products", response_model=Product)
async def create_product(product: Product, db=Depends(get_db)):
    return db.add_product(product)


@router.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, product: Product, db=Depends(get_db)):
    updated = db.update_product(product_id, product)
    if not updated:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")
    return updated


@router.delete("/products/{product_id}")
async def delete_product(product_id: str, db=Depends(get_db)):
    success = db.delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi.")
    return {"status": "success", "message": "Mahsulot o'chirildi."}


# ─── Orders ──────────────────────────────────────────────────────────────────
@router.get("/orders", response_model=List[Order])
async def list_orders(db=Depends(get_db)):
    return db.get_orders()


@router.put("/orders/{order_id}/status", response_model=Order)
async def update_order_status(order_id: str, status: str = Body(..., embed=True), db=Depends(get_db)):
    updated = db.update_order_status(order_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi.")
    return updated


# ─── Settings ────────────────────────────────────────────────────────────────
@router.get("/settings", response_model=SystemSettings)
async def get_settings(db=Depends(get_db)):
    return db.settings


@router.post("/settings", response_model=SystemSettings)
async def save_settings(settings_data: SystemSettings, db=Depends(get_db)):
    db.settings = settings_data
    db.save_settings()
    return db.settings


# ─── Image Upload ─────────────────────────────────────────────────────────────
from fastapi import UploadFile, File
import uuid

UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
async def upload_image(file: UploadFile = File(...), tenant=Depends(require_auth)):
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


# ─── Integrations ────────────────────────────────────────────────────────────
@router.get("/integrations/status")
async def get_integrations_status(db=Depends(get_db)):
    return {
        "google_sheets": sheets_service.is_connected(),
        "telegram_bot": bot_service.is_configured(),
        "ai_provider": db.settings.ai_provider
    }
