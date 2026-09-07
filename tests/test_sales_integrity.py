"""Critical invariants at the order boundary."""

import pytest
from sqlalchemy import Numeric

from app.db import repo
from app.db.models import Order, Payment, Product, Tenant


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, products):
        self.products = iter(products)
        self.added = []

    async def execute(self, _statement):
        return _Result(next(self.products))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def get(self, _model, _key):
        return None


async def _ignore_customer_link(*_args, **_kwargs):
    return None


async def test_order_reserves_stock_and_combines_duplicate_lines(monkeypatch):
    from app.services import customer_service

    monkeypatch.setattr(customer_service, "record_order", _ignore_customer_link)
    product = Product(
        tenant_id="t1",
        id="p1",
        name="Telefon",
        category="",
        price=100_000,
        currency="UZS",
        description="",
        image_urls=[],
        in_stock=True,
        stock_quantity=5,
    )
    session = _Session([product])

    order, created = await repo.create_order(
        session,
        "t1",
        "Ali",
        "+998901234567",
        [
            {"product_id": "p1", "quantity": 2, "unit_price": 1},
            {"product_id": "p1", "quantity": 1, "unit_price": 1},
        ],
    )

    assert created is True
    assert product.stock_quantity == 2
    assert order.total_amount == 300_000
    assert len(order.items) == 1
    assert order.items[0].quantity == 3
    assert order.items[0].unit_price == 100_000


async def test_order_rejects_insufficient_stock_before_writing():
    product = Product(
        tenant_id="t1",
        id="p1",
        name="Telefon",
        category="",
        price=100_000,
        currency="UZS",
        description="",
        image_urls=[],
        in_stock=True,
        stock_quantity=1,
    )
    session = _Session([product])

    with pytest.raises(ValueError, match="yetarli emas"):
        await repo.create_order(
            session,
            "t1",
            "Ali",
            "+998901234567",
            [{"product_id": "p1", "quantity": 2}],
        )

    assert product.stock_quantity == 1
    assert session.added == []


def test_money_columns_use_fixed_precision():
    columns = (
        Product.__table__.c.price,
        Order.__table__.c.total_amount,
        Payment.__table__.c.amount,
        Tenant.__table__.c.balance,
    )
    assert all(isinstance(column.type, Numeric) for column in columns)
