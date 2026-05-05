"""Тесты ValueCalculator."""

from __future__ import annotations

from core.value_calculator import ValueCalculator


def test_value_when_p_and_odds_ok():
    # Дефолтный фильтр: p ≥ 0.35 (валуйный + вероятный), odds > 1.15
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.92, actual_odds=1.20)
    assert bet.is_value
    assert bet.value_percent > 2.0


def test_no_value_when_odds_too_low():
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.95, actual_odds=1.05)
    assert not bet.is_value


def test_no_value_when_low_probability():
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.20, actual_odds=2.0)
    # p < 0.35 — не пропускает фильтр (новый дефолт)
    assert not bet.is_value


def test_value_with_strict_threshold_p55():
    # При жёстком пороге 0.90 пик с p=0.55 не должен пройти.
    calc = ValueCalculator(min_probability=0.90)
    bet = calc.calculate(probability=0.55, actual_odds=2.0)
    assert not bet.is_value


def test_suspicious_p_high_odds_high_rejected():
    # p=0.91 и кф=6 — очевидно неправильный маппинг рынка: не должен быть value
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.91, actual_odds=6.0)
    assert not bet.is_value


def test_top_value_picks_highest_with_strict_filter():
    # Тест явно использует строгий порог 0.90, как было исторически.
    calc = ValueCalculator(min_probability=0.90)
    probs = {"A": 0.92, "B": 0.95, "C": 0.60}
    odds = {"A": 1.20, "B": 1.30, "C": 3.00}
    top = calc.find_top_value(probs, odds, top_n=5)
    # Только A и B проходят фильтр, C (p<0.9) отсекается
    assert len(top) == 2
    assert top[0].value_percent >= top[1].value_percent


def test_top_value_picks_with_default_threshold():
    # На дефолтном пороге p≥0.35 — все три проходят, сортировка по value_percent.
    calc = ValueCalculator()
    probs = {"A": 0.92, "B": 0.95, "C": 0.60}
    odds = {"A": 1.20, "B": 1.30, "C": 3.00}
    top = calc.find_top_value(probs, odds, top_n=5)
    assert len(top) == 3
    # Сортировка не возрастающая: первый ≥ остальных по value_percent.
    assert top[0].value_percent >= top[-1].value_percent


def test_zero_odds_returns_no_value():
    calc = ValueCalculator()
    bet = calc.calculate(probability=0.5, actual_odds=0.0)
    assert not bet.is_value
