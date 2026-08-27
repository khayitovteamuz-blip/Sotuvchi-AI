"""Accounts inside a tenant — password resets, login/email changes, and the
session-revocation levers support needs when an account may be compromised."""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.common import get_tenant_or_404
from app.core import security
from app.core.platform_auth import require_platform_admin
from app.db.base import get_session
from app.db.models import LoginAttempt, PlatformAdmin, User, UserSession
from app.services import audit_service

router = APIRouter()


@router.post("/tenants/{tenant_id}/users/{user_id}/reset-password")
async def reset_user_password(
    tenant_id: str,
    user_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Issue a new password and return it once.

    The most common support call there is. The generated value is shown to the
    admin a single time and never stored in readable form — only its argon2
    hash goes to the database.
    """
    await get_tenant_or_404(session, tenant_id)
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")

    new_password = secrets.token_urlsafe(9)
    user.password_hash = security.hash_password(new_password)
    await session.commit()

    # Old sessions must die with the old password, or a stolen cookie survives
    # the very reset that was meant to cut it off.
    await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
    await session.execute(
        sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{user.email}"))
    )
    await session.commit()

    await audit_service.log(
        session, admin, "user_password_reset", tenant_id, {"email": user.email}, request
    )
    return {"status": "success", "email": user.email, "password": new_password}


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    email: Optional[str] = None
    password: Optional[str] = None


MIN_PASSWORD_LEN = 8


@router.patch("/tenants/{tenant_id}/users/{user_id}")
async def update_user(
    tenant_id: str,
    user_id: str,
    patch: UserPatch,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Change a business's login, its password, or switch the account off.

    The email *is* the login, so changing it and changing the password both
    invalidate every open browser session — otherwise the old credentials keep
    a stolen cookie alive past the very change meant to cut it off.
    """
    await get_tenant_or_404(session, tenant_id)
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")

    changes: dict = {}
    revoke = False
    old_email = user.email

    if patch.email is not None:
        email = patch.email.strip().lower()
        if email and email != user.email:
            if "@" not in email or "." not in email.split("@")[-1]:
                raise HTTPException(status_code=400, detail="Email noto'g'ri yozilgan.")
            taken = (await session.execute(
                select(User.id).where(User.email == email, User.id != user_id)
            )).scalar_one_or_none()
            if taken:
                raise HTTPException(status_code=409, detail="Bu email boshqa hisobga biriktirilgan.")
            changes["email"] = {"from": user.email, "to": email}
            user.email = email
            revoke = True

    if patch.password is not None and patch.password.strip():
        password = patch.password.strip()
        if len(password) < MIN_PASSWORD_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"Parol kamida {MIN_PASSWORD_LEN} ta belgidan iborat bo'lsin.",
            )
        user.password_hash = security.hash_password(password)
        changes["password"] = "set"   # never the value itself, not even in the audit log
        revoke = True

    if patch.is_active is not None and patch.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": patch.is_active}
        user.is_active = patch.is_active
        if not patch.is_active:
            revoke = True

    if not changes:
        return {"status": "unchanged"}

    await session.commit()

    if revoke:
        await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
        # The throttle counter is keyed by email; both the old and the new one
        # are cleared so a locked-out owner can use their new details at once.
        for addr in {old_email, user.email}:
            await session.execute(
                sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{addr}"))
            )
        await session.commit()

    await audit_service.log(
        session, admin, "user_update", tenant_id, {"email": user.email, **changes}, request
    )
    return {"status": "success", "email": user.email, "changes": changes}


@router.post("/tenants/{tenant_id}/unlock")
async def unlock_tenant_logins(
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """Clear the login throttle for everyone in this business.

    Someone who mistyped their password eight times is locked out for fifteen
    minutes; without this the only answer support can give them is "wait".
    """
    await get_tenant_or_404(session, tenant_id)
    emails = (
        await session.execute(select(User.email).where(User.tenant_id == tenant_id))
    ).scalars().all()
    for email in emails:
        await session.execute(sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{email}")))
    await session.commit()
    await audit_service.log(session, admin, "login_unlock", tenant_id, {"users": len(emails)}, request)
    return {"status": "success", "users": len(emails)}


@router.post("/tenants/{tenant_id}/logout-all")
async def logout_all(
    tenant_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: PlatformAdmin = Depends(require_platform_admin),
):
    """End every browser session this business has open — the containment step
    when an owner reports their account may be compromised."""
    await get_tenant_or_404(session, tenant_id)
    ids = (
        await session.execute(select(User.id).where(User.tenant_id == tenant_id))
    ).scalars().all()
    res = await session.execute(sa_delete(UserSession).where(UserSession.user_id.in_(ids)))
    await session.commit()
    await audit_service.log(session, admin, "sessions_revoked", tenant_id, {"count": res.rowcount}, request)
    return {"status": "success", "revoked": res.rowcount or 0}
