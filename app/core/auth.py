"""
Auth module — session management and FastAPI dependency for tenant auth.
Uses simple server-side session tokens stored in an in-memory dict.
Cookie name: sotuvchi_session
"""
import uuid
from typing import Dict, Optional
from fastapi import Request, HTTPException, status

# In-memory session store: { session_token: tenant_id }
_sessions: Dict[str, str] = {}

SESSION_COOKIE = "sotuvchi_session"


def create_session(tenant_id: str) -> str:
    """Create a new session token for the given tenant, return the token."""
    token = uuid.uuid4().hex
    _sessions[token] = tenant_id
    return token


def get_tenant_id_from_request(request: Request) -> Optional[str]:
    """Read session cookie and return tenant_id, or None if not logged in."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return _sessions.get(token)


def destroy_session(request: Request):
    """Invalidate the session cookie token."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)


async def require_auth(request: Request):
    """
    FastAPI dependency — returns the current Tenant or raises 401.
    Usage: tenant = Depends(require_auth)
    """
    from app.core.tenant_manager import tenant_manager
    tenant_id = get_tenant_id_from_request(request)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tizimga kirish talab qilinadi."
        )
    tenant = tenant_manager.get_by_id(tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant topilmadi yoki faol emas."
        )
    return tenant
