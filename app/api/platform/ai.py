"""A tenant's AI configuration — model catalogue and the patch endpoint that
lets an operator fix it as a support call."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core.platform_auth import require_platform_admin
from app.db import repo
from app.db.base import get_session
from app.db.models import Plan, PlatformAdmin
from app.services import ai_models, audit_service

router = APIRouter()


@router.get("/ai/models")
async def ai_model_catalog(provider: str = "", model: str = ""):
    """What the model dropdown may offer, and which entries can really answer.

    The panel needs this before it renders: a provider whose key is missing is
    still listed, greyed out with the reason, so the operator sees why a choice
    is unavailable instead of picking one that would quietly do nothing.
    """
    return {"providers": ai_models.catalog(provider, model)}


class AiPatch(BaseModel):
    system_prompt: Optional[str] = None
    ai_provider: Optional[str] = None
    model_name: Optional[str] = None
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
    tenant = await get_tenant_or_404(session, tenant_id)
    cfg = await repo.get_settings(session, tenant_id)

    # A model switch is only honoured if that model can actually serve the chat.
    # Saving a provider whose key is absent would leave the business silently on
    # the keyword engine while the panel claimed otherwise.
    if patch.ai_provider or patch.model_name:
        provider = (patch.ai_provider or cfg.ai_provider or ai_models.DEFAULT_PROVIDER).lower()
        model = patch.model_name or cfg.model_name
        if provider not in ai_models.PROVIDERS:
            raise HTTPException(status_code=400, detail="Bunday AI provayderi yo'q.")
        reason = ai_models.unavailable_reason(provider)
        if reason:
            raise HTTPException(status_code=400, detail=reason)
        # An id we don't list is allowed only if the business is already on it —
        # the dropdown shows that one as "(hozirgi)", so re-saving the profile
        # unchanged must not be rejected.
        if (patch.model_name and patch.model_name != cfg.model_name
                and not ai_models.model_meta(provider, patch.model_name)):
            raise HTTPException(
                status_code=400,
                detail=f"'{patch.model_name}' — {ai_models.PROVIDERS[provider]['title']} ro'yxatida yo'q model.",
            )
        # Tarif shu modelni sotib olmagan bo'lsa, saqlanmaydi — aks holda
        # Start tarifidagi mijoz Pro darajasidagi modelga o'tkazilib, farqni
        # platforma to'lardi. Mavjud (o'zgarmayotgan) qiymatni qayta
        # saqlashda tekshirmaymiz: pastroq tarifga tushirilgan mijoz allaqachon
        # yuqoriroq modelda bo'lishi mumkin, va profilni tegmasdan qayta
        # saqlash shu sababli rad etilmasligi kerak.
        changed = model != cfg.model_name or provider != (cfg.ai_provider or ai_models.DEFAULT_PROVIDER).lower()
        if changed:
            plan = await session.get(Plan, tenant.plan)
            max_tier = plan.max_model_tier if plan else None
            if not ai_models.tier_allowed(provider, model, max_tier):
                meta = ai_models.model_meta(provider, model) or {}
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{tenant.business_name}' — {(plan.title if plan else tenant.plan)} tarifida "
                        f"'{meta.get('title', model)}' modeli yo'q. Avval tarifni oshiring."
                    ),
                )
        patch.ai_provider = provider
        patch.model_name = model

    changes = {}
    for field in ("system_prompt", "ai_provider", "model_name", "temperature",
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
