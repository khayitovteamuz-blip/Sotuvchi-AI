"""Staff of one business — the seats the tariff has always been selling.

`max_operators` appeared on every pricing card and in the panel's usage bar,
but there was no endpoint and no screen for adding a second person, so a shop
that bought "3 operators" received one. This is that feature.

Only the owner may manage staff. An operator can work the Inbox and the
catalogue; they cannot create colleagues, spend the balance or disconnect the
bot — see `require_owner`.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.auth import hash_password, require_owner
from app.db.base import get_session
from app.db.models import LoginAttempt, User, UserSession
from app.models.tenant import EMAIL_RE, MIN_PASSWORD_LEN
from app.services import quota_service, tenant_service

logger = logging.getLogger("users_api")

router = APIRouter(prefix="/api/admin/users", tags=["Staff"])

ROLES = ("owner", "operator")


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "operator"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email noto'g'ri yozilgan.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Parol kamida {MIN_PASSWORD_LEN} ta belgidan iborat bo'lsin.")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("Rol faqat 'owner' yoki 'operator' bo'lishi mumkin.")
        return v


class UserPatch(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v is not None and v not in ROLES:
            raise ValueError("Rol faqat 'owner' yoki 'operator' bo'lishi mumkin.")
        return v


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.strftime("%Y-%m-%d") if u.created_at else None,
    }


async def _get_colleague(session: AsyncSession, tenant_id: str, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Xodim topilmadi.")
    return user


async def _count_owners(session: AsyncSession, tenant_id: str, exclude: str = "") -> int:
    rows = (
        await session.execute(
            select(User).where(
                User.tenant_id == tenant_id, User.role == "owner", User.is_active.is_(True)
            )
        )
    ).scalars().all()
    return len([u for u in rows if u.id != exclude])


@router.get("")
async def list_users(
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    rows = (
        await session.execute(
            select(User).where(User.tenant_id == user.tenant_id).order_by(User.created_at)
        )
    ).scalars().all()
    usage = await quota_service.usage(session, tenant)
    return {"users": [_out(u) for u in rows], "limit": usage["operators"]}


@router.post("")
async def create_user(
    data: UserCreate,
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Hire someone. The seat limit is checked here, where seats are spent."""
    tenant = await tenant_service.get_tenant(session, user.tenant_id)
    try:
        await quota_service.check_operators(session, tenant, adding=1)
    except quota_service.QuotaExceeded as e:
        # 402: the fix is a tariff change, not a corrected request
        raise HTTPException(status_code=402, detail=e.message)

    if await tenant_service.get_user_by_email(session, data.email):
        raise HTTPException(status_code=409, detail="Bu email allaqachon band.")

    colleague = User(
        id=f"user-{uuid.uuid4().hex[:12]}",
        tenant_id=user.tenant_id,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        full_name=data.full_name.strip() or data.email.split("@")[0],
    )
    session.add(colleague)
    await session.commit()
    logger.info(f"Tenant {user.tenant_id}: user {colleague.email} added as {colleague.role}")
    return _out(colleague)


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    patch: UserPatch,
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    colleague = await _get_colleague(session, user.tenant_id, user_id)
    changed, revoke = [], False

    # Guard both ways round: a shop with no active owner can never be managed
    # again, and that includes the owner switching their own role or account off.
    losing_owner = (
        (patch.role is not None and patch.role != "owner" and colleague.role == "owner")
        or (patch.is_active is False and colleague.role == "owner")
    )
    if losing_owner and await _count_owners(session, user.tenant_id, exclude=colleague.id) == 0:
        raise HTTPException(
            status_code=400,
            detail="Kamida bitta faol egasi qolishi kerak. Avval boshqa xodimni ega qiling.",
        )

    if patch.full_name is not None and patch.full_name.strip() != (colleague.full_name or ""):
        colleague.full_name = patch.full_name.strip()
        changed.append("full_name")
    if patch.role is not None and patch.role != colleague.role:
        colleague.role = patch.role
        changed.append("role")
        revoke = True   # a demoted operator must not keep an owner's open session
    if patch.is_active is not None and patch.is_active != colleague.is_active:
        colleague.is_active = patch.is_active
        changed.append("is_active")
        revoke = revoke or not patch.is_active
    if patch.password:
        if len(patch.password) < MIN_PASSWORD_LEN:
            raise HTTPException(
                status_code=400,
                detail=f"Parol kamida {MIN_PASSWORD_LEN} ta belgidan iborat bo'lsin.",
            )
        colleague.password_hash = hash_password(patch.password)
        changed.append("password")
        revoke = True

    if not changed:
        return {"status": "unchanged", **_out(colleague)}

    await session.commit()
    if revoke:
        await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
        await session.execute(
            sa_delete(LoginAttempt).where(LoginAttempt.key.like(f"%|{colleague.email}"))
        )
        await session.commit()
    return {"status": "success", "changed": changed, **_out(colleague)}


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Remove a colleague. Their conversations and orders stay with the shop."""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="O'zingizni o'chira olmaysiz.")
    colleague = await _get_colleague(session, user.tenant_id, user_id)
    if colleague.role == "owner" and await _count_owners(session, user.tenant_id, exclude=user_id) == 0:
        raise HTTPException(status_code=400, detail="Oxirgi egasini o'chirib bo'lmaydi.")

    await session.execute(sa_delete(UserSession).where(UserSession.user_id == user_id))
    await session.delete(colleague)
    await session.commit()
    return {"status": "success"}
