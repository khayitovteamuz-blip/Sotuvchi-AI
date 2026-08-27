"""Platform-wide AI rules: the in-process cache that keeps this off the hot
path (every AI turn reads it — see repo.py's comment on _PLATFORM_AI_TTL).

A stale-forever cache would mean a platform admin's edit never reaches a
live chat; a cache that misses every time defeats the whole point of having
one. Both failure modes are cheap to introduce by accident, so both are
tested directly against the module's cache dict rather than trusting a
manual read of the code.
"""
from app.db import repo


class _FakeSession:
    """Counts how many times the DB would actually be hit."""

    def __init__(self, row):
        self._row = row
        self.get_calls = 0

    async def get(self, _model, _pk):
        self.get_calls += 1
        return self._row


class _FakeRow:
    def __init__(self, guardrails_text="v1"):
        self.style_text = "style"
        self.guardrails_text = guardrails_text
        self.updated_by = None


def _reset_cache():
    repo._platform_ai_cache["row"] = None
    repo._platform_ai_cache["at"] = 0.0


async def test_first_read_hits_the_database():
    _reset_cache()
    session = _FakeSession(_FakeRow())
    row = await repo.get_platform_ai_settings(session)
    assert row.guardrails_text == "v1"
    assert session.get_calls == 1


async def test_second_read_within_ttl_is_served_from_cache():
    _reset_cache()
    session = _FakeSession(_FakeRow())
    await repo.get_platform_ai_settings(session)
    await repo.get_platform_ai_settings(session)
    assert session.get_calls == 1, "a cached read must not touch the database again"


async def test_read_after_ttl_expires_hits_the_database_again(monkeypatch):
    _reset_cache()
    session = _FakeSession(_FakeRow())
    await repo.get_platform_ai_settings(session)

    # Fast-forward past the TTL without sleeping in the test.
    monkeypatch.setattr(repo, "_platform_ai_cache",
                        {"row": repo._platform_ai_cache["row"],
                         "at": repo._platform_ai_cache["at"] - repo._PLATFORM_AI_TTL - 1})
    await repo.get_platform_ai_settings(session)
    assert session.get_calls == 2


async def test_missing_row_returns_none_without_caching():
    """A database that hasn't run the seed migration must not cache `None`
    forever — the very next request should try again, not stay broken."""
    _reset_cache()
    session = _FakeSession(row=None)
    assert await repo.get_platform_ai_settings(session) is None
    assert repo._platform_ai_cache["row"] is None


class _FakeSaveSession:
    """Minimal stand-in for save_platform_ai_settings: get() returns the
    existing row (or None, to exercise the create path), add()/commit() are
    recorded but do nothing."""

    def __init__(self, existing_row):
        self._row = existing_row
        self.added = []
        self.committed = False

    async def get(self, _model, _pk):
        return self._row

    def add(self, obj):
        self.added.append(obj)
        self._row = obj

    async def commit(self):
        self.committed = True


async def test_save_updates_existing_row_and_invalidates_cache():
    _reset_cache()
    repo._platform_ai_cache["row"] = _FakeRow("stale")
    repo._platform_ai_cache["at"] = 1e18  # far in the future -> still "fresh" if not invalidated

    session = _FakeSaveSession(_FakeRow("old"))
    saved = await repo.save_platform_ai_settings(session, "new style", "new guardrails", "admin@x.com")

    assert saved.guardrails_text == "new guardrails"
    assert saved.updated_by == "admin@x.com"
    assert session.committed is True
    assert repo._platform_ai_cache["row"] is None, "a save must not leave the old value cached"


async def test_save_creates_the_row_when_none_exists():
    _reset_cache()
    session = _FakeSaveSession(existing_row=None)
    saved = await repo.save_platform_ai_settings(session, "style", "guardrails", "admin@x.com")
    assert saved.id == "global"
    assert session.added, "a missing row must be created, not silently dropped"
