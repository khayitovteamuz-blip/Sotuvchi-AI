"""A tenant's AI configuration — platform-wide behaviour rules, and the patch
endpoint that lets an operator fix a tenant's own AI settings as a support
call. Model choice is not here: every tenant runs the one model set in
app/services/ai_models.py, there is nothing left to switch."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db import repo
from app.db.base import get_session
from app.db.models import PlatformAdmin
from app.services import audit_service

router = APIRouter()


# ─── Platform-wide AI rules (shared by every tenant) ───────────────────────────
# What a business owner cannot touch from their own panel: not "who the AI
# is" (name, tone, greeting, their shop's own knowledge) but "what it is
# allowed to do at all" — stay on the shop's topic, never obey an in-chat
# claim of authority, never invent a price. See app/db/models.py:PlatformAiSettings.
@router.get("/ai/rules")
async def get_ai_rules(session: AsyncSession = Depends(get_session)):
    row = await repo.get_platform_ai_settings(session)
    if not row:
        raise HTTPException(
            status_code=500,
            detail="platform_ai_settings bo'sh — migratsiya a96c7a980e29 ishga tushirilmagan.",
        )
    return {
        "style_text": row.style_text,
        "guardrails_text": row.guardrails_text,
        "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M") if row.updated_at else None,
        "updated_by": row.updated_by,
    }


class AiRulesPatch(BaseModel):
    style_text: str
    guardrails_text: str


@router.put("/ai/rules")
async def update_ai_rules(
    patch: AiRulesPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Edit the rules every tenant's AI runs under. Takes effect for chats
    already in progress within app.db.repo._PLATFORM_AI_TTL seconds — see the
    comment there for why an instant flip isn't needed."""
    if not patch.style_text.strip() or not patch.guardrails_text.strip():
        raise HTTPException(status_code=400, detail="Ikkala maydon ham bo'sh bo'lmasligi kerak.")
    await repo.save_platform_ai_settings(
        session, patch.style_text, patch.guardrails_text, admin.email
    )
    await audit_service.log(
        session, admin, "ai_rules_update", None,
        {"style_len": len(patch.style_text), "guardrails_len": len(patch.guardrails_text)},
        request,
    )
    return {"status": "success"}


class AiPatch(BaseModel):
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    bot_enabled: Optional[bool] = None
    auto_handoff_after: Optional[int] = None


@router.patch("/tenants/{tenant_id}/ai")
async def update_tenant_ai(
    tenant_id: str,
    patch: AiPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Fix a customer's AI configuration for them — the most common support call."""
    await get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)

    changes = {}
    for field in ("system_prompt", "temperature",
                  "bot_enabled", "auto_handoff_after"):
        new = getattr(patch, field)
        if new is not None and new != getattr(cfg, field):
            old = getattr(cfg, field)
            # Prompts run to thousands of characters; the log records that it
            # changed and by how much, not a copy of the whole text.
            changes[field] = (
                {"from_len": len(old or ""), "to_len": len(new)}
                if field == "system_prompt"
                else {"from": old, "to": new}
            )
            setattr(cfg, field, new)

    if not changes:
        return {"status": "unchanged"}

    await session.commit()
    await audit_service.log(session, admin, "tenant_ai_update", tenant_id, changes, request)
    return {"status": "success", "changes": changes}
