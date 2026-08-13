"""
Integrations API — connect a tenant's own Telegram bot (validate + webhook).
"""
import secrets

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth, require_owner
from app.core.config import settings
from app.db import repo
from app.db.base import get_session
from app.db.models import Tenant, User
from app.services import group_service, notify_service, routing_service
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
async def telegram_connect(token: str = Body(..., embed=True), user: User = Depends(require_owner), session: AsyncSession = Depends(get_session)):
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token bo'sh.")

    info = await bot_service.get_me(token)
    if not info:
        raise HTTPException(status_code=400, detail="Token noto'g'ri — Telegram tasdiqlamadi.")

    tenant = await session.get(Tenant, user.tenant_id)
    tenant.telegram_bot_token = token
    tenant.telegram_bot_username = info.get("username")
    # Rotate on every connect: the secret and the registered webhook are set
    # together, so a stale secret can never outlive the webhook that used it.
    tenant.telegram_webhook_secret = secrets.token_urlsafe(32)
    await session.commit()

    webhook_set = False
    note = None
    if settings.TELEGRAM_POLLING:
        # Localhost mode: the poller picks the bot up within ~30s. No public URL,
        # and no webhook (Telegram allows only one of the two).
        note = "Bot ulandi ✅ Localhost rejimi (polling) — telefoningizdan hoziroq yozib ko'ring."
    elif settings.PUBLIC_BASE_URL:
        url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/bot/webhook/{tenant.id}"
        webhook_set = await bot_service.set_webhook(token, url, tenant.telegram_webhook_secret)
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


# ─── Team groups ──────────────────────────────────────────────────────────────
@router.get("/groups")
async def groups_status(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await session.get(Tenant, user.tenant_id)
    return {
        "bot_connected": bool(tenant.telegram_bot_token),
        "bot_username": tenant.telegram_bot_username,
        "pairing_code": tenant.group_pairing_code,
        "groups": {
            "buyurtmalar": {"id": tenant.orders_group_id, "title": tenant.orders_group_title},
            "ishchi": {"id": tenant.work_group_id, "title": tenant.work_group_title},
            "operatorlar": {"id": tenant.operators_group_id, "title": tenant.operators_group_title},
        },
    }


@router.post("/groups/pair-code")
async def create_group_code(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    """Issue a code the owner sends inside the group as '/guruh <tur> <kod>'."""
    tenant = await session.get(Tenant, user.tenant_id)
    if not tenant.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Avval Telegram botni ulang.")
    tenant.group_pairing_code = group_service.generate_pairing_code()
    await session.commit()
    return {"pairing_code": tenant.group_pairing_code, "bot_username": tenant.telegram_bot_username}


@router.post("/groups/{kind}/disconnect")
async def disconnect_group(kind: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    if kind not in group_service.GROUP_KINDS:
        raise HTTPException(status_code=400, detail="Noma'lum guruh turi.")
    tenant = await session.get(Tenant, user.tenant_id)
    id_col, title_col, _ = group_service.GROUP_KINDS[kind]
    setattr(tenant, id_col, None)
    setattr(tenant, title_col, None)
    await session.commit()
    return {"status": "success"}


# ─── Notification routing ─────────────────────────────────────────────────────
@router.get("/notifications")
async def notification_routes(
    user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)
):
    """Which alert goes where, and which destinations are available."""
    tenant = await session.get(Tenant, user.tenant_id)
    cfg = await repo.get_settings(session, user.tenant_id)
    # A shop that connected its groups before routing existed has an empty map;
    # filling it from the old columns is what keeps its alerts flowing.
    await routing_service.ensure_routes(session, tenant, cfg)
    channels = await routing_service.channels(session, user.tenant_id)

    return {
        "bot_connected": bool(tenant.telegram_bot_token),
        "bot_username": tenant.telegram_bot_username,
        "pairing_code": cfg.pairing_code or tenant.group_pairing_code,
        "channels": [
            {"chat_id": c.chat_id, "kind": c.kind,
             "kind_label": routing_service.KINDS.get(c.kind, c.kind), "title": c.title}
            for c in channels
        ],
        "events": [
            {"key": key, **spec, "targets": routing_service.targets_for(cfg, key)}
            for key, spec in routing_service.EVENTS.items()
        ],
        "notify_on_handoff": cfg.notify_on_handoff,
        "notify_on_order": cfg.notify_on_order,
    }


@router.put("/notifications")
async def save_notification_routes(
    routes: dict = Body(..., embed=True),
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Save the routing table: {event: [chat_id, ...]}."""
    cfg = await repo.get_settings(session, user.tenant_id)
    known = {c.chat_id for c in await routing_service.channels(session, user.tenant_id)}

    clean: dict = {}
    for event, targets in routes.items():
        if event not in routing_service.EVENTS:
            raise HTTPException(status_code=400, detail=f"Noma'lum xabar turi: {event}")
        if isinstance(targets, str):
            targets = [targets]
        picked = [str(t) for t in (targets or []) if str(t) in known]
        if routing_service.EVENTS[event]["needs_group"]:
            # The confirm button needs someone able to press it and a name to
            # record. A channel has neither, so this is refused rather than
            # discovered later by an order nobody could confirm.
            channels = {c.chat_id: c.kind
                        for c in await routing_service.channels(session, user.tenant_id)}
            bad = [t for t in picked if channels.get(t) == "channel"]
            if bad:
                raise HTTPException(
                    status_code=400,
                    detail=f"«{routing_service.EVENTS[event]['title']}» kanalga yuborilmaydi — "
                           "tugmani bosadigan odam kerak. Guruh yoki shaxsiy chat tanlang.",
                )
        if picked:
            clean[event] = picked

    cfg.notify_routes = clean
    await session.commit()
    return {"status": "success", "routes": clean}


@router.post("/notifications/code")
async def notification_pair_code(
    user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)
):
    """One code for every kind of destination — private chat, group or channel."""
    tenant = await session.get(Tenant, user.tenant_id)
    if not tenant.telegram_bot_token:
        raise HTTPException(status_code=400, detail="Avval Telegram botni ulang.")
    cfg = await repo.get_settings(session, user.tenant_id)
    code = routing_service.new_code()
    cfg.pairing_code = code
    tenant.group_pairing_code = code
    await session.commit()
    return {"pairing_code": code, "bot_username": tenant.telegram_bot_username}


@router.delete("/notifications/channels/{chat_id}")
async def unpair_channel(
    chat_id: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)
):
    if not await routing_service.remove_channel(session, user.tenant_id, chat_id):
        raise HTTPException(status_code=404, detail="Bunday manzil yo'q.")
    cfg = await repo.get_settings(session, user.tenant_id)
    if cfg.operator_chat_id == str(chat_id):
        cfg.operator_chat_id = None
        cfg.operator_name = None
    await session.commit()
    return {"status": "success"}


@router.post("/telegram/disconnect")
async def telegram_disconnect(user: User = Depends(require_owner), session: AsyncSession = Depends(get_session)):
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant.telegram_bot_token:
        await bot_service.delete_webhook(tenant.telegram_bot_token)
    tenant.telegram_bot_token = None
    tenant.telegram_bot_username = None
    tenant.telegram_webhook_secret = None
    await session.commit()
    return {"status": "success"}
