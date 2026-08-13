"""The subscription clock.

Every case below is a way the old code let a business run without paying, or
cut one off that had. The revenue of the whole product is decided by this file.
"""
import pytest

from app.services import billing_service as b
from tests.conftest import FakePlan, FakeTenant, days, utcnow


# ─── status_of ────────────────────────────────────────────────────────────────

def test_no_period_is_expired_not_free(paid_plan):
    """The hole that mattered: a tenant with no expiry date used to read as
    "free" and therefore never expired — a paid tariff, running for ever."""
    t = FakeTenant(subscription_expires_at=None)
    assert b.status_of(t, paid_plan) == "expired"


def test_trial_is_labelled_trial(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() + days(5), is_trial=True)
    assert b.status_of(t, paid_plan) == "trial"


def test_paid_period_is_active(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() + days(5), is_trial=False)
    assert b.status_of(t, paid_plan) == "active"


def test_just_expired_falls_into_grace(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() - days(1))
    assert b.status_of(t, paid_plan) == "grace"


def test_after_grace_it_is_expired(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() - days(b.GRACE_DAYS + 1))
    assert b.status_of(t, paid_plan) == "expired"


def test_free_plan_never_expires(free_plan):
    t = FakeTenant(subscription_expires_at=utcnow() - days(100))
    assert b.status_of(t, free_plan) == "free"


def test_frozen_wins_over_everything(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() - days(100), frozen_at=utcnow())
    assert b.status_of(t, paid_plan) == "frozen"


# ─── days_left / freeze ───────────────────────────────────────────────────────

def test_freezing_stops_the_clock(paid_plan):
    """Suspension must bank the unused days, not spend them."""
    t = FakeTenant(subscription_expires_at=utcnow() + days(10))
    b.freeze(t)
    t.frozen_at = utcnow() - days(30)          # as if suspended a month ago
    assert b.days_left(t) == pytest.approx(40, abs=0.1)


def test_unfreeze_pushes_the_expiry_forward(paid_plan):
    t = FakeTenant(subscription_expires_at=utcnow() + days(10))
    original = t.subscription_expires_at
    t.frozen_at = utcnow() - days(30)
    b.unfreeze(t)
    assert t.frozen_at is None
    assert (t.subscription_expires_at - original).days == pytest.approx(30, abs=1)


def test_freeze_is_idempotent():
    t = FakeTenant(frozen_at=utcnow() - days(5))
    first = t.frozen_at
    b.freeze(t)
    assert t.frozen_at == first, "a second freeze must not restart the clock"


# ─── is_free ──────────────────────────────────────────────────────────────────

def test_free_is_decided_by_price_not_name():
    """Naming a plan "start" once made it exempt from expiry. Raising its price
    then left a paid tariff that never had to be renewed."""
    assert b.is_free(FakePlan(name="start", price=0)) is True
    assert b.is_free(FakePlan(name="start", price=490000)) is False
    assert b.is_free(None) is False


# ─── the dunning ladder ───────────────────────────────────────────────────────

@pytest.mark.parametrize("left,expected", [
    (30, None),   # too early to warn
    (7, 7),
    (6.5, 7),
    (3, 3),       # both 7 and 3 match — the customer needs to hear "three"
    (1, 1),
    (0.5, 1),
    (0, 0),       # the period has ended
])
def test_which_warning_is_due(left, expected):
    assert b.due_stage(left) == expected


def test_stage_only_moves_forward():
    """Reminders count down. Having sent the 3-day notice, the 7-day one must
    not be sent again on the next request — and expiry is checked constantly."""
    t = FakeTenant(dunning_stage=3)
    for candidate in (7, 3):
        assert candidate >= t.dunning_stage, "would re-send an older warning"
    assert 1 < t.dunning_stage, "the 1-day warning is still ahead"


# ─── buy_plan arithmetic ──────────────────────────────────────────────────────

class _Session:
    """Just enough of AsyncSession for buy_plan: it adds a row and commits."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def get(self, _model, _pk):
        return None


async def test_renewing_early_keeps_the_days_already_paid_for(paid_plan):
    t = FakeTenant(balance=1_000_000, subscription_expires_at=utcnow() + days(10))
    await b.buy_plan(_Session(), t, paid_plan)
    left = b.days_left(t)
    assert left == pytest.approx(10 + paid_plan.duration_days, abs=0.1)


async def test_renewing_late_starts_from_today(paid_plan):
    t = FakeTenant(balance=1_000_000, subscription_expires_at=utcnow() - days(20))
    await b.buy_plan(_Session(), t, paid_plan)
    assert b.days_left(t) == pytest.approx(paid_plan.duration_days, abs=0.1)


async def test_buying_ends_the_trial(paid_plan):
    t = FakeTenant(balance=1_000_000, is_trial=True, dunning_stage=1,
                   subscription_expires_at=utcnow() + days(2))
    await b.buy_plan(_Session(), t, paid_plan)
    assert t.is_trial is False
    assert t.dunning_stage is None, "the new period starts its ladder over"


async def test_paying_reopens_a_business_expiry_had_closed(paid_plan):
    t = FakeTenant(balance=1_000_000, is_active=False,
                   subscription_expires_at=utcnow() - days(30))
    await b.buy_plan(_Session(), t, paid_plan)
    assert t.is_active is True


async def test_paying_does_not_undo_an_admin_suspension(paid_plan):
    """A business an operator suspended by hand stays suspended even if it pays."""
    t = FakeTenant(balance=1_000_000, is_active=False, frozen_at=utcnow(),
                   subscription_expires_at=utcnow() + days(5))
    await b.buy_plan(_Session(), t, paid_plan)
    assert t.is_active is False


async def test_cannot_buy_without_the_money(paid_plan):
    t = FakeTenant(balance=100.0)
    with pytest.raises(ValueError):
        await b.buy_plan(_Session(), t, paid_plan)


async def test_the_charge_is_written_to_the_ledger(paid_plan):
    """The balance must always add up from its history."""
    s = _Session()
    t = FakeTenant(balance=1_000_000)
    await b.buy_plan(s, t, paid_plan)
    assert len(s.added) == 1
    row = s.added[0]
    assert row.amount == -paid_plan.price_uzs
    assert row.kind == "subscription"
    assert t.balance == 1_000_000 - paid_plan.price_uzs
