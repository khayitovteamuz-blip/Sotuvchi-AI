"""Shared fixtures.

These tests deliberately avoid the database. The rules worth protecting here —
when a subscription expires, what a quota allows, whether an order is valid —
are pure functions of a few fields, and testing them against a live Postgres
would make the suite slow, order-dependent and impossible to run in CI without
credentials. Where a database object is needed, a light stand-in with the same
attributes is enough.
"""
from datetime import datetime, timedelta, timezone

import pytest


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def days(n: float) -> timedelta:
    return timedelta(days=n)


class FakeTenant:
    """Only the fields the billing rules read."""

    def __init__(self, **kw):
        self.id = kw.get("id", "tenant-test")
        self.business_name = kw.get("business_name", "Test do'kon")
        self.plan = kw.get("plan", "start")
        self.is_active = kw.get("is_active", True)
        self.balance = kw.get("balance", 0.0)
        self.subscription_expires_at = kw.get("subscription_expires_at")
        self.frozen_at = kw.get("frozen_at")
        self.is_trial = kw.get("is_trial", False)
        self.auto_renew = kw.get("auto_renew", True)
        self.dunning_stage = kw.get("dunning_stage")
        self.telegram_bot_token = kw.get("telegram_bot_token")
        self.orders_group_id = kw.get("orders_group_id")


class FakePlan:
    def __init__(self, name="start", price=490000.0, duration=30, **kw):
        self.name = name
        self.title = kw.get("title", name.title())
        self.price_uzs = price
        self.duration_days = duration
        self.max_products = kw.get("max_products", 99)
        self.max_ai_messages_monthly = kw.get("max_ai_messages_monthly", 1000)
        self.max_operators = kw.get("max_operators", 3)


@pytest.fixture
def tenant():
    return FakeTenant()


@pytest.fixture
def paid_plan():
    return FakePlan()


@pytest.fixture
def free_plan():
    return FakePlan(name="bepul", price=0.0)
