"""
Telegram webhook — routed per tenant: /api/bot/webhook/{tenant_id}
"""
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.services import tenant_service
from app.services.bot_service import bot_service

logger = logging.getLogger("bot_webhook")

router = APIRouter(prefix="/api/bot", tags=["Telegram Bot Webhook"])

SECRET_HEADER = "x-telegram-bot-api-secret-token"


@router.post("/webhook/{tenant_id}")
async def telegram_webhook(tenant_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Receive updates for a specific tenant's bot."""
    tenant = await tenant_service.get_tenant(session, tenant_id)
    if not tenant or not tenant.telegram_bot_token:
        # Always 200 so Telegram doesn't retry a misconfigured tenant forever
        return {"status": "ignored"}

    # The tenant id travels in a public URL, so it authenticates nobody: without
    # this check anyone who saw one could post fake orders as a real customer.
    # Telegram echoes the secret registered via setWebhook; nothing else can.
    expected = tenant.telegram_webhook_secret or ""
    provided = request.headers.get(SECRET_HEADER, "")
    if not expected or not hmac.compare_digest(provided, expected):
        logger.warning(f"Rejected webhook for tenant {tenant_id}: bad secret token")
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        update = await request.json()
        await bot_service.handle_update(session, tenant, update)
        return {"status": "ok"}
    except Exception as e:
        # 200 on purpose: a bug in our handler must not make Telegram redeliver
        # the same update forever.
        logger.exception(f"Webhook handling failed for tenant {tenant_id}")
        return {"status": "error", "message": str(e)}
