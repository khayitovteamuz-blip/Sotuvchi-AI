"""
Auth API — Register, Login, Logout, and Me endpoints.
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from app.models.tenant import TenantLogin, TenantRegister
from app.core.tenant_manager import tenant_manager
from app.core.auth import create_session, destroy_session, require_auth, SESSION_COOKIE

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register")
async def register(data: TenantRegister):
    """Register a new business (tenant)."""
    try:
        tenant = tenant_manager.register(
            business_name=data.business_name,
            email=data.email,
            password=data.password,
        )
        return {"status": "success", "tenant": tenant.to_safe_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
async def login(data: TenantLogin):
    """Authenticate tenant and set session cookie."""
    tenant = tenant_manager.authenticate(data.email, data.password)
    if not tenant:
        raise HTTPException(status_code=401, detail="Email yoki parol noto'g'ri.")

    token = create_session(tenant.id)
    response = JSONResponse(content={
        "status": "success",
        "tenant": tenant.to_safe_dict()
    })
    # HttpOnly cookie — JS can't read it, prevents XSS theft
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Destroy session."""
    destroy_session(request)
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me")
async def me(tenant=Depends(require_auth)):
    """Return current logged-in tenant info."""
    return tenant.to_safe_dict()
