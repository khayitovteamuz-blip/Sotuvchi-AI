"""
Telegram webhook — routed per tenant: /api/bot/webhook/{tenant_id}
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.services import tenant_service
from app.services.bot_service import bot_service

router = APIRouter(prefix="/api/bot", tags=["Telegram Bot Webhook"])


@router.post("/webhook/{tenant_id}")
async def telegram_webhook(tenant_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Receive updates for a specific tenant's bot."""
    try:
        tenant = await tenant_service.get_tenant(session, tenant_id)
        if not tenant or not tenant.telegram_bot_token:
            # Always 200 so Telegram doesn't retry a misconfigured tenant forever
            return {"status": "ignored"}
        update = await request.json()
        await bot_service.handle_update(session, tenant, update)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
