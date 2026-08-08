"""
Auth API — Register, Login, Logout, Me (Postgres-backed, session cookie).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

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
async def login(data: TenantLogin, session: AsyncSession = Depends(get_session)):
    user = await tenant_service.authenticate(session, data.email, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")

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
