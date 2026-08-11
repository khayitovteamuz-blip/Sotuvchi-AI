"""
Platform-admin authentication — deliberately separate from tenant auth.

A platform admin reads and writes across every business on the service, so this
shares nothing with `app.core.auth` beyond password hashing: different table,
different session store, different cookie. A stolen business-panel cookie is
useless here, and no bug in tenant code can mint a platform session.

There is no registration endpoint. Admins are created with
`python -m scripts.create_platform_admin`, which requires shell access to the
host — the internet cannot reach it.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import client_ip
from app.core.config import settings
from app.db.base import get_session
from app.db.models import PlatformAdmin, PlatformSession

PLATFORM_COOKIE = "sotuvchi_platform"

# Shorter than the 7-day business session: this cookie opens every customer's
# data, so an unattended browser should stop being a way in sooner.
SESSION_TTL = timedelta(hours=12)
TOUCH_INTERVAL = timedelta(minutes=30)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def set_platform_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=PLATFORM_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.PUBLIC_BASE_URL.startswith("https://"),
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


async def create_platform_session(
    db: AsyncSession, admin_id: str, request: Optional[Request] = None
) -> str:
    now = datetime.now(timezone.utc)
    await db.execute(delete(PlatformSession).where(PlatformSession.expires_at < now))

    token = secrets.token_urlsafe(32)
    db.add(
        PlatformSession(
            token_hash=_hash_token(token),
            admin_id=admin_id,
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
            ip=client_ip(request) if request else None,
            user_agent=(request.headers.get("user-agent", "")[:256] or None) if request else None,
        )
    )
    await db.commit()
    return token


async def destroy_platform_session(db: AsyncSession, request: Request) -> None:
    token = request.cookies.get(PLATFORM_COOKIE)
    if not token:
        return
    await db.execute(
        delete(PlatformSession).where(PlatformSession.token_hash == _hash_token(token))
    )
    await db.commit()


async def require_platform_admin(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> PlatformAdmin:
    """Dependency for the whole platform router.

    Attached once at the router rather than per endpoint, so a route added later
    cannot forget it — that omission would expose every tenant's data.
    """
    token = request.cookies.get(PLATFORM_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Platforma paneliga kirish talab qilinadi.",
        )

    row = (
        await db.execute(
            select(PlatformSession, PlatformAdmin)
            .join(PlatformAdmin, PlatformAdmin.id == PlatformSession.admin_id)
            .where(PlatformSession.token_hash == _hash_token(token))
        )
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya topilmadi. Qaytadan kiring.",
        )

    sess, admin = row
    now = datetime.now(timezone.utc)

    if sess.expires_at <= now:
        await db.execute(
            delete(PlatformSession).where(PlatformSession.token_hash == sess.token_hash)
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya muddati tugadi. Qaytadan kiring.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Hisob faol emas."
        )

    if now - sess.last_seen_at > TOUCH_INTERVAL:
        sess.last_seen_at = now
        sess.expires_at = now + SESSION_TTL
        await db.commit()

    return admin
