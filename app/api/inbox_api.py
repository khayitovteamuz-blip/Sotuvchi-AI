"""
Inbox API — live conversations, operator reply, and handoff (tenant-scoped).
This is the product's main screen: seeing what the AI said and stepping in.
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth
from app.db import repo
from app.db.base import get_session
from app.db.models import User
from app.services import tenant_service
from app.services.bot_service import bot_service

router = APIRouter(prefix="/api/inbox", tags=["Inbox"])


def _photos_from_meta(meta) -> list:
    """Pull product images out of a message's recorded tool calls."""
    out = []
    for call in (meta or {}).get("tools", []):
        if call.get("name") == "send_product_photo":
            out.extend((call.get("result") or {}).get("photos") or [])
    return out


@router.get("/conversations")
async def list_conversations(status: str = "all", user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    return await repo.list_conversations(session, user.tenant_id, status)


@router.get("/waiting-count")
async def waiting_count(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    """Lightweight poll target so the panel can badge pending handoffs anywhere.

    Returns the ids too: the panel alerts once per conversation, so replying
    silences it until that customer writes again.
    """
    ids = await repo.waiting_conversations(session, user.tenant_id)
    return {"waiting": len(ids), "ids": ids}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    conv = await repo.get_conversation(session, user.tenant_id, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Suhbat topilmadi.")
    await repo.mark_conversation_read(session, user.tenant_id, conv_id)
    msgs = await repo.conversation_messages(session, conv_id)
    return {
        "conversation": {
            "id": conv.id, "channel": conv.channel, "status": conv.status,
            "customer_name": conv.customer_name or "Mijoz",
            "customer_phone": conv.customer_phone, "external_id": conv.external_id,
            "assigned_user_name": conv.assigned_user_name,
            "handoff_reason": conv.handoff_reason,
        },
        "messages": [
            {"sender": m.sender, "text": m.text, "model_name": m.model_name,
             "tokens": m.tokens, "intent": m.intent,
             # images the AI sent, so the operator sees the whole exchange
             "photos": _photos_from_meta(m.meta),
             "created_at": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else None}
            for m in msgs
        ],
    }


@router.post("/conversations/{conv_id}/reply")
async def operator_reply(conv_id: str, text: str = Body(..., embed=True), user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    conv = await repo.get_conversation(session, user.tenant_id, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Suhbat topilmadi.")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Xabar bo'sh.")

    # Sending as a human => take over the conversation and claim it
    if conv.status == "ai":
        conv.status = "operator"
    conv.assigned_user_id = user.id
    conv.assigned_user_name = user.full_name or user.email
    await repo.add_message(session, user.tenant_id, conv, "operator", text)

    # Deliver to the customer's channel
    if conv.channel == "telegram" and conv.external_id:
        tenant = await tenant_service.get_tenant(session, user.tenant_id)
        if tenant and tenant.telegram_bot_token:
            await bot_service.send_message(tenant.telegram_bot_token, conv.external_id, text)

    return {"status": "success", "conversation_status": conv.status}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    """Remove a conversation and its messages (test chatter shouldn't sit next to real ones)."""
    conv = await repo.get_conversation(session, user.tenant_id, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Suhbat topilmadi.")
    await session.delete(conv)   # messages cascade
    await session.commit()
    return {"status": "success"}


@router.post("/conversations/{conv_id}/status")
async def set_status(conv_id: str, status: str = Body(..., embed=True), user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    if status not in ("ai", "operator", "closed"):
        raise HTTPException(status_code=400, detail="Noto'g'ri status.")
    conv = await repo.set_conversation_status(session, user.tenant_id, conv_id, status)
    if not conv:
        raise HTTPException(status_code=404, detail="Suhbat topilmadi.")
    return {"status": "success", "conversation_status": conv.status}
