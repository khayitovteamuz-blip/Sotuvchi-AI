"""Encryption of secrets held for customers.

A Telegram bot token is the shop's entire channel to its customers. These tests
guard the two properties that matter: a stored value is not readable, and a
value written before encryption existed still works.
"""
import pytest

from app.core import crypto


@pytest.fixture
def keyed(monkeypatch):
    from cryptography.fernet import Fernet
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    monkeypatch.setattr(crypto, "_client_failed", False, raising=False)
    monkeypatch.setattr(crypto, "_warned", False)
    yield
    monkeypatch.setattr(crypto, "_fernet", None)


TOKEN = "8894880269:AAEYKSE1BqwWiHetE80B24n4XUr2xSBD2qE"


def test_a_round_trip_returns_the_token(keyed):
    assert crypto.decrypt(crypto.encrypt(TOKEN)) == TOKEN


def test_the_stored_value_does_not_contain_the_token(keyed):
    """The point of the exercise: a database dump must not be a token dump."""
    stored = crypto.encrypt(TOKEN)
    assert TOKEN not in stored
    assert stored.startswith(crypto.PREFIX)


def test_encrypting_twice_does_not_double_wrap(keyed):
    once = crypto.encrypt(TOKEN)
    assert crypto.encrypt(once) == once
    assert crypto.decrypt(once) == TOKEN


def test_a_plaintext_value_still_works(keyed):
    """Rows written before encryption existed pass straight through — this is
    what lets the rollout be gradual instead of a flag day."""
    assert crypto.decrypt(TOKEN) == TOKEN


def test_two_encryptions_differ(keyed):
    """Fernet includes a nonce, so identical tokens do not produce identical
    ciphertext — otherwise a dump would still reveal which shops share one."""
    assert crypto.encrypt(TOKEN) != crypto.encrypt(TOKEN)


def test_without_a_key_values_pass_through(monkeypatch):
    """No key configured is a warning, not an outage: a running platform must
    not go down because a config value has not been set yet."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    monkeypatch.setattr(crypto, "_fernet", None)
    assert crypto.encrypt(TOKEN) == TOKEN
    assert crypto.decrypt(TOKEN) == TOKEN


def test_empty_values_are_left_alone(keyed):
    assert crypto.encrypt(None) is None
    assert crypto.encrypt("") == ""
    assert crypto.decrypt(None) is None


def test_a_wrong_key_fails_loudly_not_silently(keyed):
    """Returning ciphertext would send Telegram a nonsense token and the bot
    would go quiet with no explanation. None at least reaches the logs."""
    from cryptography.fernet import Fernet
    from app.core.config import settings
    stored = crypto.encrypt(TOKEN)
    settings.ENCRYPTION_KEY = Fernet.generate_key().decode()
    crypto._fernet = None
    assert crypto.decrypt(stored) is None
