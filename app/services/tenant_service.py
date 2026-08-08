"""
Tenant/User service — registration and authentication on Postgres.
Replaces the old JSON-file TenantManager.
"""
import uuid
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, verify_password
from app.core.config import settings
from app.db.models import Tenant, TenantSettings, User


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    res = await session.execute(select(User).where(User.email == email.lower()))
    return res.scalar_one_or_none()


async def register(
    session: AsyncSession, business_name: str, email: str, password: str
) -> Tuple[Tenant, User]:
    """Create a new business (Tenant) + its owner (User) + default settings."""
    email = email.strip().lower()
    if await get_user_by_email(session, email):
        raise ValueError("Bu email allaqachon ro'yxatdan o'tgan.")

    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    tenant = Tenant(id=tenant_id, business_name=business_name.strip())
    session.add(tenant)
    await session.flush()  # ensure tenant row exists before FKs

    owner = User(
        id=f"user-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(password),
        role="owner",
        full_name=business_name.strip(),
    )
    session.add(owner)
    session.add(TenantSettings(tenant_id=tenant_id, system_prompt=settings.DEFAULT_SYSTEM_PROMPT))
    await session.commit()
    return tenant, owner


async def authenticate(session: AsyncSession, email: str, password: str) -> Optional[User]:
    user = await get_user_by_email(session, email.strip().lower())
    if user and user.is_active and verify_password(password, user.password_hash):
        return user
    return None


async def get_tenant(session: AsyncSession, tenant_id: str) -> Optional[Tenant]:
    return await session.get(Tenant, tenant_id)


def safe_user_dict(user: User, tenant: Tenant) -> dict:
    """Shape the frontend expects (business_name + email at top level)."""
    return {
        "id": tenant.id,
        "user_id": user.id,
        "business_name": tenant.business_name,
        "email": user.email,
        "role": user.role,
        "plan": tenant.plan,
        "is_active": tenant.is_active,
    }
