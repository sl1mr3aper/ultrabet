"""Подтверждаем сортировку value bets по убыванию валуйности и наличие fair."""

from __future__ import annotations

from itertools import pairwise

from core.value_calculator import ValueCalculator


def test_find_top_value_sorted_desc():
    calc = ValueCalculator(min_odds=1.20, min_value_percent=0.0)
    probs = {"a": 0.55, "b": 0.40, "c": 0.30}
    odds = {"a": 2.10, "b": 3.50, "c": 4.00}
    out = calc.find_top_value(probs, odds, top_n=10)
    assert len(out) >= 1
    for prev, nxt in pairwise(out):
        assert prev.value_percent >= nxt.value_percent


def test_value_bet_has_fair_odds():
    bet = ValueCalculator().calculate(
        probability=0.5, actual_odds=2.10, market_key="x"
    )
    assert abs(bet.fair_odds - 2.0) < 1e-9


def test_value_calculation_correct():
    bet = ValueCalculator().calculate(probability=0.55, actual_odds=2.10, market_key="x")
    assert abs(bet.value_percent - 15.5) < 0.01


def test_no_value_when_odds_below_min():
    calc = ValueCalculator(min_odds=1.50, min_value_percent=0.0)
    out = calc.find_top_value({"a": 0.99}, {"a": 1.10}, top_n=5)
    assert out == []


def test_no_value_when_value_below_threshold():
    calc = ValueCalculator(min_odds=1.20, min_value_percent=10.0)
    out = calc.find_top_value({"a": 0.50}, {"a": 2.10}, top_n=5)
    assert out == []  # value 5% < 10%
