"""Тесты нормализации коэф/вероятностей."""

from __future__ import annotations

import pytest

from services.normalizer import (
    american_to_decimal,
    clamp_probability,
    decimal_to_american,
    decimal_to_fractional,
    fair_odds_from_probs,
    fractional_to_decimal,
    implied_from_odds,
    margin_percent,
    strip_margin,
)


def test_implied_from_odds():
    assert abs(implied_from_odds(2.0) - 0.5) < 1e-9
    assert abs(implied_from_odds(4.0) - 0.25) < 1e-9
    assert implied_from_odds(1.0) == 1.0


def test_strip_margin_normalizes_to_1():
    probs = [0.55, 0.30, 0.25]  # sum=1.10 (margin 10%)
    normalized = strip_margin(probs)
    assert abs(sum(normalized) - 1.0) < 1e-9


def test_strip_margin_empty():
    assert strip_margin([0, 0, 0]) == [0, 0, 0]


def test_fair_odds():
    fo = fair_odds_from_probs([0.5, 0.25, 0.25])
    assert abs(fo[0] - 2.0) < 1e-9
    assert abs(fo[1] - 4.0) < 1e-9


def test_margin_percent():
    assert abs(margin_percent([0.55, 0.30, 0.25]) - 10.0) < 1e-9


@pytest.mark.parametrize("dec,amer", [(2.0, 100), (3.0, 200), (1.5, -200), (1.25, -400)])
def test_decimal_american_roundtrip(dec, amer):
    assert decimal_to_american(dec) == amer
    assert abs(american_to_decimal(amer) - dec) < 1e-3


def test_decimal_to_fractional_basic():
    assert decimal_to_fractional(3.5) == "5/2"
    assert decimal_to_fractional(2.0) == "1/1"
    assert decimal_to_fractional(1.0) == "0/1"


def test_fractional_to_decimal():
    assert abs(fractional_to_decimal("5/2") - 3.5) < 1e-9
    assert abs(fractional_to_decimal("1/1") - 2.0) < 1e-9
    assert fractional_to_decimal("garbage") == 0.0
    assert fractional_to_decimal("1/0") == 0.0


def test_clamp_probability():
    assert clamp_probability(0.0) == 0.005
    assert clamp_probability(1.0) == 0.995
    assert clamp_probability(0.5) == 0.5
