"""Encryption for secrets held on behalf of customers.

Today that means Telegram bot tokens. A token is the shop's entire channel to
its customers: whoever holds it can read every incoming message and answer as
the shop. Stored in plain text, one database dump hands an attacker every
business on the platform at once.

Design decisions worth stating, because both are trade-offs:

* **Values are tagged.** Ciphertext is stored as `enc:v1:<token>`, so a row can
  be recognised at a glance and a table can hold a mix while the migration
  rolls through. Anything without the tag is read as-is.
* **A missing key is not fatal.** Without `ENCRYPTION_KEY` the values are
  stored as they always were and a warning is logged once. The alternative —
  refusing to start — would take a running platform down over a config change,
  and an operator who has not yet generated a key still needs their shops
  answering customers.

Losing the key means losing the tokens: every business would have to reconnect
its bot. Keep it with the database credentials, not next to them.
"""
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("crypto")

PREFIX = "enc:v1:"

_fernet = None
_warned = False


def _cipher():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    if not settings.ENCRYPTION_KEY:
        if not _warned:
            logger.warning(
                "ENCRYPTION_KEY sozlanmagan — Telegram bot tokenlari bazada ochiq "
                "matnda saqlanadi. Kalit yaratish: python -c \"from "
                "cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
            _warned = True
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    except Exception as e:
        if not _warned:
            logger.error(f"ENCRYPTION_KEY yaroqsiz, shifrlash o'chirildi: {e}")
            _warned = True
        return None
    return _fernet


def encrypt(value: Optional[str]) -> Optional[str]:
    """Ciphertext for storage, or the value unchanged if no key is configured."""
    if not value or value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        return value
    return PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    """The usable secret. Values written before encryption pass straight through."""
    if not value or not value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        # The key was removed after data was encrypted with it. Returning the
        # ciphertext would send Telegram a nonsense token; None at least makes
        # the failure legible in the logs.
        logger.error("Shifrlangan qiymat bor, lekin ENCRYPTION_KEY yo'q.")
        return None
    try:
        return cipher.decrypt(value[len(PREFIX):].encode()).decode()
    except Exception as e:
        logger.error(f"Qiymatni ochib bo'lmadi (kalit almashganmi?): {e}")
        return None


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value and value.startswith(PREFIX))
