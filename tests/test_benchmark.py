"""Runs eval/benchmark.py's checkable=True scenarios in CI.

These 35 (of 100) scenarios don't need a live model — they check guard.py
and profanity.py directly, so a future change that breaks one is caught
here instead of the next time a real customer tries it. The other 65
(narx/ombor/yetkazib_berish/etiroz/mavzudan_chiqish/aralash) need an AI
response to judge and are not run in CI — see eval/run_benchmark.py and
REJA: "Loyiha Kalibr", Bosqich 00.
"""
import pytest

from app.services import guard, profanity
from eval.benchmark import SCENARIOS

_CHECKABLE = [s for s in SCENARIOS if s.get("checkable")]


def test_benchmark_has_the_expected_shape():
    assert len(SCENARIOS) == 100
    assert len(_CHECKABLE) == 35


@pytest.mark.parametrize("s", _CHECKABLE, ids=[s["id"] for s in _CHECKABLE])
def test_checkable_scenario(s):
    if "expect_guard" in s:
        assert guard.detect(s["input"]) == s["expect_guard"], s["input"]
    if "expect_profanity" in s:
        assert profanity.hits(s["input"]) == s["expect_profanity"], s["input"]
