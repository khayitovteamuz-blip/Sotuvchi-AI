"""
Telegram webhook — routed per tenant: /api/bot/webhook/{tenant_id}
"""
import hmac
import logging
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.services import tenant_service
from app.services.bot_service import bot_service

logger = logging.getLogger("bot_webhook")

router = APIRouter(prefix="/api/bot", tags=["Telegram Bot Webhook"])

SECRET_HEADER = "x-telegram-bot-api-secret-token"

# Recently handled (tenant, update_id) pairs. In memory on purpose: Telegram
# retries within seconds, so a short local window catches every real duplicate
# without a database write on the hot path. With several workers each keeps its
# own window — a retry that lands on a different worker still gets through, so
# this narrows the race rather than closing it. The durable fix is a unique
# index on the message, which belongs with the wider outbox work.
_SEEN_LIMIT = 2000
_seen_updates: "OrderedDict[str, None]" = OrderedDict()


def _remember(tenant_id: str, update_id) -> bool:
    """True if this update is new; False if we have just handled it."""
    if update_id is None:
        return True
    key = f"{tenant_id}:{update_id}"
    if key in _seen_updates:
        return False
    _seen_updates[key] = None
    while len(_seen_updates) > _SEEN_LIMIT:
        _seen_updates.popitem(last=False)
    return True


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

    # Telegram redelivers an update when it does not get a prompt 200 — and it
    # is prompt only when our handler is fast, which an AI turn is not. Without
    # this guard the same message ran twice and could create two orders.
    if not _remember(tenant_id, update.get("update_id")):
        logger.info(f"Duplicate update {update.get('update_id')} for {tenant_id} — skipped")
        return {"status": "duplicate"}

    try:
        await bot_service.handle_update(session, tenant, update)
        return {"status": "ok"}
    except Exception:
        # 200 on purpose: a bug in our handler must not make Telegram redeliver
        # the same update forever. The reason stays in our log — echoing the
        # exception text back would hand an attacker our internals.
        logger.exception(f"Webhook handling failed for tenant {tenant_id}")
        return {"status": "error"}
