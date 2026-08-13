"""Tariff limits.

The seat limit is the one that was sold on every pricing card while nothing
enforced it — because there was no way to add a second person at all.
"""
import pytest

from app.services import quota_service as q
from tests.conftest import FakePlan


class _DB:
    """Returns fixed counts; the arithmetic under test is in quota_service."""

    def __init__(self, plan, products=0, operators=0):
        self._plan, self._products, self._operators = plan, products, operators

    async def get(self, _model, _pk):
        return self._plan


@pytest.fixture(autouse=True)
def _counts(monkeypatch):
    async def products(db, tenant_id):
        return db._products

    async def operators(db, tenant_id):
        return db._operators

    async def plan_of(db, tenant):
        return db._plan

    monkeypatch.setattr(q, "count_products", products)
    monkeypatch.setattr(q, "count_operators", operators)
    monkeypatch.setattr(q, "get_plan", plan_of)


async def test_room_for_one_more_product(tenant):
    await q.check_products(_DB(FakePlan(max_products=99), products=98), tenant)


async def test_the_last_slot_is_allowed(tenant):
    """99 of 99 must be reachable — an off-by-one here sells 98."""
    await q.check_products(_DB(FakePlan(max_products=99), products=98), tenant, adding=1)


async def test_over_the_line_is_refused(tenant):
    with pytest.raises(q.QuotaExceeded) as e:
        await q.check_products(_DB(FakePlan(max_products=99), products=99), tenant)
    assert e.value.resource == "products"
    assert "99" in e.value.message, "the message must name the limit the owner has to raise"


async def test_unlimited_plan_never_blocks(tenant):
    await q.check_products(_DB(FakePlan(max_products=None), products=100_000), tenant)


async def test_seat_limit_is_enforced(tenant):
    await q.check_operators(_DB(FakePlan(max_operators=3), operators=2), tenant)
    with pytest.raises(q.QuotaExceeded) as e:
        await q.check_operators(_DB(FakePlan(max_operators=3), operators=3), tenant)
    assert e.value.resource == "operators"


async def test_a_bulk_import_is_checked_as_a_whole(tenant):
    """Importing 50 rows into 60 free slots is fine; into 40 it is not — and it
    must be refused before half the file has been written."""
    await q.check_products(_DB(FakePlan(max_products=100), products=40), tenant, adding=50)
    with pytest.raises(q.QuotaExceeded):
        await q.check_products(_DB(FakePlan(max_products=100), products=60), tenant, adding=50)
