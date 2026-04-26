"""Тесты парлей-калькулятора."""

from __future__ import annotations

from services.parlay import ParlayLeg, calculate_parlay, describe_risk


def test_empty_parlay_returns_none():
    assert calculate_parlay([]) is None


def test_invalid_leg_returns_none():
    assert calculate_parlay([ParlayLeg("x", 0.5, 0.9)]) is None
    assert calculate_parlay([ParlayLeg("x", 0.0, 2.0)]) is None
    assert calculate_parlay([ParlayLeg("x", 1.5, 2.0)]) is None


def test_two_legs_multiplies_odds():
    legs = [ParlayLeg("A", 0.6, 2.0), ParlayLeg("B", 0.5, 3.0)]
    r = calculate_parlay(legs)
    assert r is not None
    assert abs(r.total_odds - 6.0) < 1e-9
    assert abs(r.combined_probability - 0.3) < 1e-9


def test_value_pct_computes():
    legs = [ParlayLeg("A", 0.6, 2.0), ParlayLeg("B", 0.5, 3.0)]
    r = calculate_parlay(legs)
    # 0.3 * 6 - 1 = 0.8 → 80%
    assert abs(r.value_percent - 80.0) < 1e-9


def test_fair_total_odds():
    legs = [ParlayLeg("A", 0.5, 2.0), ParlayLeg("B", 0.5, 2.0)]
    r = calculate_parlay(legs)
    # fair = 1/(0.5*0.5) = 4
    assert abs(r.fair_total_odds - 4.0) < 1e-9


def test_describe_risk_levels():
    class FakeR:
        def __init__(self, o):
            self.total_odds = o
    assert "низкий" in describe_risk(FakeR(1.5))
    assert "умеренный" in describe_risk(FakeR(3.0))
    assert "высокий" in describe_risk(FakeR(10.0))
    assert "очень высокий" in describe_risk(FakeR(30.0))
    assert "экстремальный" in describe_risk(FakeR(100.0))
