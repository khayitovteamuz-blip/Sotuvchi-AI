"""Platform administrator accounts — who can open /boshqaruv."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.platform_auth import require_platform_admin
from app.db.base import get_session
from app.db.models import PlatformAdmin, PlatformSession
from app.services import audit_service

router = APIRouter()


@router.get("/admins")
async def list_admins(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(PlatformAdmin).order_by(PlatformAdmin.created_at))
    ).scalars().all()
    return [
        {
            "id": a.id,
            "email": a.email,
            "full_name": a.full_name,
            "is_active": a.is_active,
            "created_at": a.created_at.strftime("%Y-%m-%d") if a.created_at else None,
            "last_login_at": a.last_login_at.strftime("%Y-%m-%d %H:%M") if a.last_login_at else None,
        }
        for a in rows
    ]


class AdminCreate(BaseModel):
    email: str
    full_name: Optional[str] = None
    password: str


@router.post("/admins")
async def create_admin(
    data: AdminCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Only an existing admin can mint another one — the shell script stays the
    way in for the very first account."""
    if len(data.password) < 10:
        raise HTTPException(status_code=400, detail="Parol kamida 10 belgi bo'lishi kerak.")
    email = data.email.strip().lower()
    exists = (
        await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="Bu email allaqachon ro'yxatdan o'tgan.")

    session.add(
        PlatformAdmin(
            id=f"padmin-{uuid.uuid4().hex[:12]}",
            email=email,
            full_name=(data.full_name or "").strip() or None,
            password_hash=security.hash_password(data.password),
        )
    )
    await session.commit()
    await audit_service.log(session, admin, "admin_create", None, {"email": email}, request)
    return {"status": "success", "email": email}


class AdminPatch(BaseModel):
    is_active: Optional[bool] = None


@router.patch("/admins/{admin_id}")
async def update_admin(
    admin_id: str,
    patch: AdminPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    target = await session.get(PlatformAdmin, admin_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin topilmadi.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="O'z hisobingizni o'chira olmaysiz.")
    if patch.is_active is None or patch.is_active == target.is_active:
        return {"status": "unchanged"}

    # Guard against locking everyone out of the platform panel
    if not patch.is_active:
        active = (
            await session.execute(
                select(func.count()).select_from(PlatformAdmin)
                .where(PlatformAdmin.is_active.is_(True))
            )
        ).scalar() or 0
        if active <= 1:
            raise HTTPException(status_code=400, detail="Oxirgi faol adminni o'chirib bo'lmaydi.")

    target.is_active = patch.is_active
    await session.commit()
    if not patch.is_active:
        await session.execute(sa_delete(PlatformSession).where(PlatformSession.admin_id == admin_id))
        await session.commit()
    await audit_service.log(
        session, admin, "admin_update", None, {"email": target.email, "is_active": patch.is_active}, request
    )
    return {"status": "success"}
