"""
Auth — server-side session tokens + FastAPI dependency returning the current User.

Sessions map a cookie token to a user_id (in-memory; swap for Redis in prod).
Passwords are sha256-hashed (kept consistent with the data migrated from JSON).
"""
import hashlib
import uuid
from typing import Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import User

# In-memory session store: { session_token: user_id }
_sessions: Dict[str, str] = {}

SESSION_COOKIE = "sotuvchi_session"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == password_hash


def create_session(user_id: str) -> str:
    token = uuid.uuid4().hex
    _sessions[token] = user_id
    return token


def get_user_id_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return _sessions.get(token)


def destroy_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)


async def require_auth(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency — returns the current User or raises 401."""
    user_id = get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tizimga kirish talab qilinadi.")
    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Foydalanuvchi topilmadi yoki faol emas.")
    return user
