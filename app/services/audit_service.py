"""
Platform audit trail.

Every write a platform admin makes to a customer's account is recorded. When a
business asks "who changed my tariff / who read my orders", the panel has to be
able to answer — and the answer has to survive the admin account being deleted,
which is why the email is stored alongside the id.
"""
import logging
from typing import Optional

from fastapi import Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_ip
from app.db.models import PlatformAdmin, PlatformAuditLog

logger = logging.getLogger("audit")


async def log(
    db: AsyncSession,
    admin: PlatformAdmin,
    action: str,
    tenant_id: Optional[str] = None,
    details: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Record an action. Commits, so call it after the change it describes."""
    db.add(
        PlatformAuditLog(
            admin_id=admin.id,
            admin_email=admin.email,
            action=action,
            tenant_id=tenant_id,
            details=details,
            ip=client_ip(request) if request else None,
        )
    )
    await db.commit()
    logger.info(f"[audit] {admin.email} {action} tenant={tenant_id} {details or ''}")


async def recent(db: AsyncSession, limit: int = 100, tenant_id: Optional[str] = None) -> list:
    q = select(PlatformAuditLog).order_by(desc(PlatformAuditLog.created_at)).limit(limit)
    if tenant_id:
        q = q.where(PlatformAuditLog.tenant_id == tenant_id)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "admin_email": r.admin_email,
            "action": r.action,
            "tenant_id": r.tenant_id,
            "details": r.details,
            "ip": r.ip,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in rows
    ]
