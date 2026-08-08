"""
Integrations API — connect a tenant's own Telegram bot (validate + webhook).
"""
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth
from app.core.config import settings
from app.db import repo
from app.db.base import get_session
from app.db.models import Tenant, User
from app.services import notify_service
from app.services.bot_service import bot_service
from app.services.telegram_poller import telegram_poller

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


@router.get("/telegram")
async def telegram_status(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await session.get(Tenant, user.tenant_id)
    return {
        "connected": bool(tenant.telegram_bot_token),
        "username": tenant.telegram_bot_username,
        "public_url_configured": bool(settings.PUBLIC_BASE_URL),
        "polling_enabled": settings.TELEGRAM_POLLING,
        "polling_active": telegram_poller.is_polling(tenant.id),
    }


@router.post("/telegram/connect")
async def telegram_connect(token: str = Body(..., embed=True), user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token bo'sh.")

    info = await bot_service.get_me(token)
    if not info:
        raise HTTPException(status_code=400, detail="Token noto'g'ri — Telegram tasdiqlamadi.")

    tenant = await session.get(Tenant, user.tenant_id)
    tenant.telegram_bot_token = token
    tenant.telegram_bot_username = info.get("username")
    if not tenant.telegram_webhook_secret:
        tenant.telegram_webhook_secret = uuid.uuid4().hex[:16]
    await session.commit()

    webhook_set = False
    note = None
    if settings.TELEGRAM_POLLING:
        # Localhost mode: the poller picks the bot up within ~30s. No public URL,
        # and no webhook (Telegram allows only one of the two).
        note = "Bot ulandi ✅ Localhost rejimi (polling) — telefoningizdan hoziroq yozib ko'ring."
    elif settings.PUBLIC_BASE_URL:
        url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/bot/webhook/{tenant.id}"
        webhook_set = await bot_service.set_webhook(token, url)
        note = None if webhook_set else "Webhook o'rnatilmadi — PUBLIC_BASE_URL ni tekshiring."
    else:
        note = ("Bot ulandi, lekin na polling na PUBLIC_BASE_URL yoqilgan — "
                "xabarlar kelmaydi. TELEGRAM_POLLING=true qiling.")

    return {"status": "success", "username": info.get("username"), "webhook_set": webhook_set, "note": note}


# ─── Operator alerts (pairing) ────────────────────────────────────────────────
@router.get("/operator")
async def operator_status(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await session.get(Tenant, user.tenant_id)
    cfg = await repo.get_settings(session, user.tenant_id)
    return {
        "paired": bool(cfg.operator_chat_id),
        "operator_name": cfg.operator_name,
        "pairing_code": cfg.pairing_code,
        "bot_username": tenant.telegram_bot_username,
        "bot_connected": bool(tenant.telegram_bot_token),
        "notify_on_handoff": cfg.notify_on_handoff,
        "notify_on_order": cfg.notify_on_order,
    }


@router.post("/operator/pair-code")
async def create_pairing_code(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    """Issue a fresh pairing code; the owner sends it to the bot as /operator CODE."""
    tenant = await session.get(Tenant, user.tenant_id)
    if not tenant.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Avval Telegram botni ulang.")
    cfg = await repo.get_settings(session, user.tenant_id)
    cfg.pairing_code = notify_service.generate_pairing_code()
    await session.commit()
    return {
        "pairing_code": cfg.pairing_code,
        "bot_username": tenant.telegram_bot_username,
        "instruction": f"Telegram'da @{tenant.telegram_bot_username} botiga yozing: /operator {cfg.pairing_code}",
    }


@router.post("/operator/unpair")
async def unpair_operator(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    cfg = await repo.get_settings(session, user.tenant_id)
    cfg.operator_chat_id = None
    cfg.operator_name = None
    await session.commit()
    return {"status": "success"}


@router.post("/operator/notifications")
async def set_notifications(
    notify_on_handoff: bool = Body(True, embed=True),
    notify_on_order: bool = Body(True, embed=True),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    cfg = await repo.get_settings(session, user.tenant_id)
    cfg.notify_on_handoff = notify_on_handoff
    cfg.notify_on_order = notify_on_order
    await session.commit()
    return {"status": "success"}


@router.post("/telegram/disconnect")
async def telegram_disconnect(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant.telegram_bot_token:
        await bot_service.delete_webhook(tenant.telegram_bot_token)
    tenant.telegram_bot_token = None
    tenant.telegram_bot_username = None
    await session.commit()
    return {"status": "success"}
