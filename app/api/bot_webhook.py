"""
Telegram webhook — routed per tenant: /api/bot/webhook/{tenant_id}
"""
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.services import telegram_updates, tenant_service
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
    except Exception:
        return {"status": "ignored"}

    update_id = update.get("update_id")
    # A Postgres claim is shared by every worker and survives restarts. In-memory
    # sets only reduced duplicates; they could not prevent two workers creating
    # the same order from one Telegram retry.
    if not await telegram_updates.claim(session, tenant_id, update_id):
        logger.info(f"Duplicate update {update_id} for {tenant_id} — skipped")
        return {"status": "duplicate"}

    try:
        await bot_service.handle_update(session, tenant, update)
        await telegram_updates.complete(session, tenant_id, update_id)
        return {"status": "ok"}
    except Exception as exc:
        logger.exception(f"Webhook handling failed for tenant {tenant_id}")
        # A failed SQL statement leaves the session unusable until rollback.
        # Mark the claim retryable and return 500 so Telegram delivers it again.
        await session.rollback()
        await telegram_updates.fail(session, tenant_id, update_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="Webhook processing failed")
