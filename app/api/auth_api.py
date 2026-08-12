"""
Auth API — Register, Login, Logout, Me (Postgres-backed, session cookie).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import (
    SESSION_COOKIE,
    client_ip,
    create_session,
    destroy_session,
    require_auth,
    set_session_cookie,
)
from app.db.base import get_session
from app.db.models import User
from app.models.tenant import TenantLogin, TenantRegister
from app.services import tenant_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register")
async def register(data: TenantRegister, request: Request, session: AsyncSession = Depends(get_session)):
    # Sign-up was wide open: one script could have filled the database with
    # tenants, each carrying its own settings and quota rows. The login
    # throttle already knows how to count and lock a key, so it is reused —
    # eight new shops from one address in fifteen minutes is well past normal.
    throttle_key = f"register|{client_ip(request)}"
    allowed, wait = await security.check_login_allowed(session, throttle_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Juda ko'p urinish. {max(1, wait // 60)} daqiqadan keyin qayta urinib ko'ring.",
        )

    try:
        tenant, owner = await tenant_service.register(
            session, data.business_name, data.email, data.password
        )
    except ValueError as e:
        await security.record_login_failure(session, throttle_key)
        raise HTTPException(status_code=400, detail=str(e))

    await security.record_login_failure(session, throttle_key)
    return {"status": "success", "tenant": tenant_service.safe_user_dict(owner, tenant)}


@router.post("/login")
async def login(data: TenantLogin, request: Request, session: AsyncSession = Depends(get_session)):
    # Two counters. The first is per IP+account and trips quickly; the second
    # ignores the address entirely, so an attacker rotating IPs (or forging
    # X-Forwarded-For) still runs into a wall on the account itself.
    throttle_key = f"{client_ip(request)}|{data.email.strip().lower()}"
    account_key = security.account_key(data.email)

    for key in (throttle_key, account_key):
        allowed, wait = await security.check_login_allowed(session, key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Juda ko'p urinish. {max(1, wait // 60)} daqiqadan keyin qayta urinib ko'ring.",
            )

    user = await tenant_service.authenticate(session, data.email, data.password)
    if not user:
        await security.record_login_failure(session, throttle_key)
        await security.record_login_failure(
            session, account_key, security.ACCOUNT_MAX_ATTEMPTS, security.ACCOUNT_LOCKOUT
        )
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")
    await security.record_login_success(session, throttle_key)
    await security.record_login_success(session, account_key)

    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    token = await create_session(session, user.id, request)
    response = JSONResponse(content={
        "status": "success",
        "tenant": tenant_service.safe_user_dict(user, tenant),
    })
    set_session_cookie(response, token)
    return response


@router.post("/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    await destroy_session(session, request)
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me")
async def me(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    return tenant_service.safe_user_dict(user, tenant)
