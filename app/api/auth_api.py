"""
Auth API — Register, Login, Logout, Me (Postgres-backed, session cookie).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import (
    SESSION_COOKIE,
    create_session,
    destroy_session,
    require_auth,
)
from app.db.base import get_session
from app.db.models import User
from app.models.tenant import TenantLogin, TenantRegister
from app.services import tenant_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _client_ip(request: Request) -> str:
    """Real client IP when running behind a reverse proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register")
async def register(data: TenantRegister, session: AsyncSession = Depends(get_session)):
    try:
        tenant, owner = await tenant_service.register(
            session, data.business_name, data.email, data.password
        )
        return {"status": "success", "tenant": tenant_service.safe_user_dict(owner, tenant)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
async def login(data: TenantLogin, request: Request, session: AsyncSession = Depends(get_session)):
    # Throttle per IP+account: without this a script can try passwords forever
    throttle_key = f"{_client_ip(request)}|{data.email.strip().lower()}"
    allowed, wait = security.check_login_allowed(throttle_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Juda ko'p urinish. {max(1, wait // 60)} daqiqadan keyin qayta urinib ko'ring.",
        )

    user = await tenant_service.authenticate(session, data.email, data.password)
    if not user:
        security.record_login_failure(throttle_key)
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")
    security.record_login_success(throttle_key)

    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    token = create_session(user.id)
    response = JSONResponse(content={
        "status": "success",
        "tenant": tenant_service.safe_user_dict(user, tenant),
    })
    response.set_cookie(
        key=SESSION_COOKIE, value=token,
        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    destroy_session(request)
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me")
async def me(user: User = Depends(require_auth), session: AsyncSession = Depends(get_session)):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    return tenant_service.safe_user_dict(user, tenant)
