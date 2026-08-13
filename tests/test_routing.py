"""Which alert goes where.

Every case here is a way the old code sent something to the wrong place — or to
one place when it should have reached two.
"""

from app.services import routing_service as r
from tests.conftest import FakeTenant


class FakeCfg:
    def __init__(self, routes=None, **kw):
        self.notify_routes = routes
        self.operator_chat_id = kw.get("operator_chat_id")
        self.operator_name = kw.get("operator_name")
        self.pairing_code = kw.get("pairing_code")


# ─── targets_for ──────────────────────────────────────────────────────────────

def test_an_event_reaches_everyone_routed_to_it():
    cfg = FakeCfg({"handoff": ["555", "-100999"]})
    assert r.targets_for(cfg, "handoff") == ["555", "-100999"]


def test_an_unrouted_event_is_switched_off():
    """Absence is the off switch — a shop that wants no order pings unticks
    every destination, and nothing is sent."""
    assert r.targets_for(FakeCfg({"order": []}), "order") == []
    assert r.targets_for(FakeCfg({}), "order") == []
    assert r.targets_for(FakeCfg(None), "order") == []
    assert r.targets_for(None, "order") == []


def test_a_single_id_written_by_hand_still_works():
    assert r.targets_for(FakeCfg({"order": "555"}), "order") == ["555"]


def test_ids_are_compared_as_text():
    """Telegram ids arrive as ints from the API and as strings from the panel;
    a mismatch here silently routes nothing."""
    assert r.targets_for(FakeCfg({"order": [555]}), "order") == ["555"]


# ─── default_routes: the old behaviour, exactly ───────────────────────────────

def test_defaults_reproduce_the_previous_destinations():
    tenant = FakeTenant()
    tenant.orders_group_id = "-100orders"
    tenant.work_group_id = "-100work"
    tenant.operators_group_id = "-100ops"
    cfg = FakeCfg(operator_chat_id="777")

    routes = r.default_routes(tenant, cfg)
    assert routes["customer_waiting"] == ["777"]
    assert routes["billing"] == ["777"]
    assert routes["receipt"] == ["-100orders"]
    assert routes["delivery"] == ["-100work"]
    # An escalation went to the owner AND the operators' group
    assert routes["handoff"] == ["777", "-100ops"]


def test_there_is_no_separate_new_order_alert():
    """It fired one line before the receipt on the same order — two messages,
    seconds apart, saying the same thing."""
    assert "order" not in r.EVENTS
    tenant = FakeTenant()
    tenant.orders_group_id = "-100orders"
    tenant.work_group_id = tenant.operators_group_id = None
    assert "order" not in r.default_routes(tenant, FakeCfg(operator_chat_id="777"))


def test_a_shop_without_groups_still_hears_about_a_sale():
    """No orders group: the receipt goes to the owner's chat, which is where
    the old separate ping used to land."""
    tenant = FakeTenant()
    tenant.orders_group_id = tenant.work_group_id = tenant.operators_group_id = None
    routes = r.default_routes(tenant, FakeCfg(operator_chat_id="777"))
    assert routes["receipt"] == ["777"]


def test_delivery_falls_back_to_the_orders_group():
    """Exactly what send_to_work_group did: `work_group_id or orders_group_id`."""
    tenant = FakeTenant()
    tenant.orders_group_id = "-100orders"
    tenant.work_group_id = None
    tenant.operators_group_id = None
    routes = r.default_routes(tenant, FakeCfg())
    assert routes["delivery"] == ["-100orders"]


def test_billing_falls_back_to_the_orders_group():
    tenant = FakeTenant()
    tenant.orders_group_id = "-100orders"
    tenant.work_group_id = None
    tenant.operators_group_id = None
    routes = r.default_routes(tenant, FakeCfg(operator_chat_id=None))
    assert routes["billing"] == ["-100orders"]


def test_a_shop_with_nothing_paired_gets_no_routes():
    tenant = FakeTenant()
    tenant.orders_group_id = tenant.work_group_id = tenant.operators_group_id = None
    assert r.default_routes(tenant, FakeCfg()) == {}


# ─── the button-carrying events ───────────────────────────────────────────────

def test_only_the_button_events_require_a_group():
    """A Telegram channel has nobody to tap 'confirmed' and no name to record."""
    assert r.EVENTS["receipt"]["needs_group"] is True
    assert r.EVENTS["delivery"]["needs_group"] is True
    for key in ("handoff", "customer_waiting", "billing"):
        assert r.EVENTS[key]["needs_group"] is False, key


def test_every_event_is_described_for_the_panel():
    for key, spec in r.EVENTS.items():
        assert spec["title"] and spec["hint"], key
