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
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

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
# In-process counters. Fine for a single worker; move to Redis when the app
# runs on more than one process.
_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 15 * 60
_LOCKOUT_SECONDS = 15 * 60

_attempts: Dict[str, List[float]] = defaultdict(list)
_locked_until: Dict[str, float] = {}


def _prune(key: str, now: float) -> None:
    _attempts[key] = [t for t in _attempts[key] if now - t < _WINDOW_SECONDS]


def check_login_allowed(key: str) -> Tuple[bool, int]:
    """Returns (allowed, seconds_to_wait). Key is IP + email."""
    now = time.time()
    until = _locked_until.get(key, 0)
    if until > now:
        return False, int(until - now)
    _prune(key, now)
    return True, 0


def record_login_failure(key: str) -> None:
    now = time.time()
    _prune(key, now)
    _attempts[key].append(now)
    if len(_attempts[key]) >= _MAX_ATTEMPTS:
        _locked_until[key] = now + _LOCKOUT_SECONDS
        _attempts[key].clear()
        logger.warning(f"Login locked for {_LOCKOUT_SECONDS // 60} min: {key}")


def record_login_success(key: str) -> None:
    _attempts.pop(key, None)
    _locked_until.pop(key, None)
