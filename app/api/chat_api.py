"""
Chat API — the in-panel AI sandbox / test chat (tenant-scoped, authenticated).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth
from app.db import repo
from app.db.base import get_session
from app.db.models import User
from app.models.schema import ChatRequest, ChatResponse
from app.services import tenant_service
from app.services.ai_agent import ai_agent

router = APIRouter(prefix="/api/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    request: ChatRequest,
    user: User = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas.")

    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    conversation = await repo.get_or_create_conversation(
        session, user.tenant_id, channel="web",
        external_id=request.session_id, customer_name=request.user_name,
    )
    return await ai_agent.generate_response(
        session, tenant, conversation, request.message, request.user_name or "Mijoz"
    )
