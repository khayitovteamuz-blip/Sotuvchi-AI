"""
Platform login — a separate router because it must be reachable *before*
there is a session (the rest of app.api.platform requires one).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import client_ip
from app.core.platform_auth import (
    PLATFORM_COOKIE,
    create_platform_session,
    destroy_platform_session,
    require_platform_admin,
    set_platform_cookie,
)
from app.db.base import get_session
from app.db.models import PlatformAdmin
from app.services import audit_service

auth_router = APIRouter(prefix="/api/platform/auth", tags=["Platform Auth"])


class PlatformLogin(BaseModel):
    email: str
    password: str


@auth_router.post("/login")
async def platform_login(
    data: PlatformLogin, request: Request, session: AsyncSession = Depends(get_session)
):
    # Same throttle table as the business panel, but a distinct key prefix so a
    # locked business login cannot lock the operator out of their own platform.
    throttle_key = f"platform|{client_ip(request)}|{data.email.strip().lower()}"
    # This one account opens every business on the platform, so it also gets
    # the address-independent counter — rotating IPs must not buy more tries.
    account_key = security.account_key(f"platform|{data.email}")

    for key in (throttle_key, account_key):
        allowed, wait = await security.check_login_allowed(session, key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Juda ko'p urinish. {max(1, wait // 60)} daqiqadan keyin urinib ko'ring.",
            )

    admin = (
        await session.execute(
            select(PlatformAdmin).where(PlatformAdmin.email == data.email.strip().lower())
        )
    ).scalars().first()

    ok, needs_rehash = (False, False)
    if admin and admin.is_active:
        ok, needs_rehash = security.verify_password(data.password, admin.password_hash)

    if not ok:
        await security.record_login_failure(session, throttle_key)
        await security.record_login_failure(
            session, account_key, security.ACCOUNT_MAX_ATTEMPTS, security.ACCOUNT_LOCKOUT
        )
        # One message for every failure mode: a distinct "no such admin" reply
        # would confirm which emails are platform accounts.
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")

    await security.record_login_success(session, throttle_key)
    await security.record_login_success(session, account_key)
    if needs_rehash:
        admin.password_hash = security.hash_password(data.password)
    admin.last_login_at = func.now()
    await session.commit()

    token = await create_platform_session(session, admin.id, request)
    await audit_service.log(session, admin, "login", request=request)

    response = JSONResponse(
        content={"status": "success", "admin": {"email": admin.email, "full_name": admin.full_name}}
    )
    set_platform_cookie(response, token)
    return response


@auth_router.post("/logout")
async def platform_logout(request: Request, session: AsyncSession = Depends(get_session)):
    await destroy_platform_session(session, request)
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(PLATFORM_COOKIE)
    return response


@auth_router.get("/me")
async def platform_me(admin: PlatformAdmin = Depends(require_platform_admin)):
    return {"email": admin.email, "full_name": admin.full_name, "id": admin.id}
