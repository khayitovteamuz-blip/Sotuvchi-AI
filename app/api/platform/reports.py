"""CSV export and the platform audit log."""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.tenants import list_tenants
from app.db.base import get_session
from app.services import audit_service

router = APIRouter()


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


@router.get("/audit")
async def audit_log(
    tenant_id: Optional[str] = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    return await audit_service.recent(session, limit=min(limit, 500), tenant_id=tenant_id)
