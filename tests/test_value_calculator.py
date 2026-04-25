"""Тесты ValueCalculator."""

from __future__ import annotations

from core.value_calculator import ValueCalculator


def test_value_when_odds_too_high():
    calc = ValueCalculator(min_odds=1.20, min_value_percent=2.0)
    bet = calc.calculate(probability=0.55, actual_odds=2.20)
    assert bet.is_value
    assert bet.value_percent > 2.0


def test_no_value_when_odds_too_low():
    calc = ValueCalculator(min_odds=1.20, min_value_percent=2.0)
    bet = calc.calculate(probability=0.55, actual_odds=1.10)
    assert not bet.is_value


def test_no_value_when_neg_value():
    calc = ValueCalculator(min_odds=1.20, min_value_percent=2.0)
    bet = calc.calculate(probability=0.30, actual_odds=2.0)
    assert not bet.is_value


def test_top_value_picks_highest():
    calc = ValueCalculator(min_value_percent=0.0, min_odds=1.05)
    probs = {"A": 0.55, "B": 0.40, "C": 0.20}
    odds = {"A": 1.90, "B": 3.00, "C": 6.00}
    top = calc.find_top_value(probs, odds, top_n=2)
    assert len(top) == 2
    assert top[0].value_percent >= top[1].value_percent


def test_zero_odds_returns_no_value():
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.5, actual_odds=0.0)
    assert not bet.is_value
