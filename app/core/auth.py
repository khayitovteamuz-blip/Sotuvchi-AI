"""
Auth — Postgres-backed session tokens + FastAPI dependency returning the current User.

Sessions used to be a module-level dict. That logged everyone out on every
restart and broke outright beyond one worker, since a request served by worker B
cannot see a token worker A handed out. They now live in the `sessions` table.

The cookie carries a random token; the table stores only its SHA-256, so a
leaked database hands an attacker no usable sessions.

Latency note: looking the session up costs nothing extra. `require_auth` already
had to fetch the User on every request, and the session row is joined into that
same query — still one round trip to the database.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.db.base import get_session
from app.db.models import Tenant, User, UserSession
from app.services import billing_service

SESSION_COOKIE = "sotuvchi_session"
SESSION_TTL = timedelta(days=7)

# How stale last_seen_at may get before we refresh it. Writing on every request
# would add a round trip to a database ~100ms away just to update a timestamp.
TOUCH_INTERVAL = timedelta(hours=1)


# Hashing lives in app.core.security (argon2id + legacy sha256 upgrade path).
# Re-exported so existing callers keep working.
hash_password = security.hash_password


def _hash_token(token: str) -> str:
    """Tokens are 256-bit random, so a plain SHA-256 is enough — there is
    nothing to brute-force and no need for a slow KDF here."""
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    """Real client IP when running behind a reverse proxy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie.

    `secure` follows the deployment: over HTTPS the cookie must never travel on
    plain HTTP, but forcing the flag on localhost would stop the panel working
    over http://127.0.0.1.
    """
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.PUBLIC_BASE_URL.startswith("https://"),
        max_age=int(SESSION_TTL.total_seconds()),
    )


async def create_session(
    db: AsyncSession, user_id: str, request: Optional[Request] = None
) -> str:
    """Issue a new session and return the raw token for the cookie."""
    now = datetime.now(timezone.utc)

    # Sweep expired rows here rather than on a timer: logins are rare, and the
    # index on expires_at keeps this cheap.
    await db.execute(delete(UserSession).where(UserSession.expires_at < now))

    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user_id,
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
            ip=client_ip(request) if request else None,
            user_agent=(request.headers.get("user-agent", "")[:256] or None) if request else None,
        )
    )
    await db.commit()
    return token


async def destroy_session(db: AsyncSession, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return
    await db.execute(
        delete(UserSession).where(UserSession.token_hash == _hash_token(token))
    )
    await db.commit()


async def destroy_all_sessions(db: AsyncSession, user_id: str) -> None:
    """Log a user out everywhere — for use after a password change or lockout."""
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await db.commit()


async def require_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency — returns the current User or raises 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tizimga kirish talab qilinadi.",
        )

    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == _hash_token(token))
        )
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya topilmadi. Qaytadan kiring.",
        )

    sess, user = row
    now = datetime.now(timezone.utc)

    if sess.expires_at <= now:
        await db.execute(
            delete(UserSession).where(UserSession.token_hash == sess.token_hash)
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessiya muddati tugadi. Qaytadan kiring.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Foydalanuvchi topilmadi yoki faol emas.",
        )

    # A tariff that ran out closes the business. Evaluated here rather than
    # on a timer: a timer lives in one worker and the others never see it.
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is not None:
        await billing_service.enforce_expiry(db, tenant)
        if not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Obuna muddati tugagan yoki hisob to'xtatilgan. "
                       "Tarifni yangilash uchun qo'llab-quvvatlashga murojaat qiling.",
            )

    # Sliding expiry: someone working all week should not be logged out mid-task.
    if now - sess.last_seen_at > TOUCH_INTERVAL:
        sess.last_seen_at = now
        sess.expires_at = now + SESSION_TTL
        await db.commit()

    return user
