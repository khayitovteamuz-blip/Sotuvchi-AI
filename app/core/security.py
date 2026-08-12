"""
Password hashing and login throttling.

Passwords were sha256 with no salt — one GPU tries billions of those per second,
so any leaked table would be plaintext within hours. Argon2id is memory-hard and
deliberately slow, which is what makes stolen hashes worthless.

Old hashes still verify: on a correct login the password is silently re-hashed
with argon2, so no one is forced to reset anything.
"""
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import case, delete, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoginAttempt

logger = logging.getLogger("security")

# Defaults are the argon2-cffi recommended profile (64 MiB, 3 passes).
_ph = PasswordHasher()

LEGACY_HASH_LEN = 64  # sha256 hex digest


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, stored: str) -> Tuple[bool, bool]:
    """Check a password. Returns (ok, needs_rehash).

    needs_rehash is True for legacy sha256 hashes and for argon2 hashes made
    with weaker parameters than we use today.
    """
    if not stored:
        return False, False

    # Legacy sha256: constant-time compare, then flag for upgrade
    if len(stored) == LEGACY_HASH_LEN and "$" not in stored:
        ok = hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
        return ok, ok

    try:
        _ph.verify(stored, password)
        return True, _ph.check_needs_rehash(stored)
    except VerifyMismatchError:
        return False, False
    except InvalidHashError:
        logger.warning("Stored password hash is malformed")
        return False, False


# ─── Login throttling ─────────────────────────────────────────────────────────
# Counters live in Postgres, not in the process. Per-worker tallies would let an
# attacker get MAX_ATTEMPTS *per worker*, and a deploy would clear every lockout.
MAX_ATTEMPTS = 8
WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)

# A second counter keyed on the account alone, because the first one is keyed
# on IP+email and an attacker who can vary the source address — or forge
# X-Forwarded-For behind a proxy that trusts every hop — gets a fresh budget
# with every change. This one they cannot escape.
#
# The threshold is deliberately far above the per-IP one: an account-level lock
# is also a way to lock a competitor out of their own shop, so it must sit well
# beyond anything a real person mistyping their password would reach.
ACCOUNT_MAX_ATTEMPTS = 30
ACCOUNT_LOCKOUT = timedelta(minutes=10)


async def check_login_allowed(db: AsyncSession, key: str) -> Tuple[bool, int]:
    """Returns (allowed, seconds_to_wait). Key is IP + email."""
    row = await db.get(LoginAttempt, key)
    if not row or not row.locked_until:
        return True, 0
    now = datetime.now(timezone.utc)
    if row.locked_until > now:
        return False, int((row.locked_until - now).total_seconds())
    return True, 0


async def record_login_failure(
    db: AsyncSession, key: str, max_attempts: int = MAX_ATTEMPTS,
    lockout: timedelta = LOCKOUT,
) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - WINDOW

    # Rows that are neither locked nor inside a live window are dead weight
    await db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.window_start < cutoff,
            or_(LoginAttempt.locked_until.is_(None), LoginAttempt.locked_until < now),
        )
    )

    # One statement, so two workers racing on the same key cannot both read 7
    # and each write 8. Inside ON CONFLICT, the bare column is the stored row's
    # value — the window resets once it has gone stale.
    stmt = (
        pg_insert(LoginAttempt)
        .values(key=key, fail_count=1, window_start=now)
        .on_conflict_do_update(
            index_elements=[LoginAttempt.key],
            set_={
                "fail_count": case(
                    (LoginAttempt.window_start < cutoff, 1),
                    else_=LoginAttempt.fail_count + 1,
                ),
                "window_start": case(
                    (LoginAttempt.window_start < cutoff, now),
                    else_=LoginAttempt.window_start,
                ),
            },
        )
        .returning(LoginAttempt.fail_count)
    )
    fails = (await db.execute(stmt)).scalar_one()

    if fails >= max_attempts:
        await db.execute(
            update(LoginAttempt)
            .where(LoginAttempt.key == key)
            .values(locked_until=now + lockout, fail_count=0)
        )
        logger.warning(f"Login locked for {int(lockout.total_seconds()) // 60} min: {key}")

    await db.commit()


def account_key(email: str) -> str:
    """Throttle key that does not include the client's address."""
    return f"account|{email.strip().lower()}"


async def record_login_success(db: AsyncSession, key: str) -> None:
    await db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
    await db.commit()
