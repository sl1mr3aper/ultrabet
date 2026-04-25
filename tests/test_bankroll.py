"""Тесты Kelly-калькулятора."""

from __future__ import annotations

import math

from core.bankroll import (
    break_even_probability,
    expected_value_percent,
    kelly_fraction,
    recommend_stake,
)


def test_kelly_zero_when_no_edge():
    # вероятность ровно соответствует справедливому коэффициенту
    p = 0.5
    odds = 2.0
    assert kelly_fraction(p, odds) == 0.0


def test_kelly_positive_with_edge():
    p = 0.55
    odds = 2.10
    f = kelly_fraction(p, odds)
    assert 0 < f < 1


def test_kelly_zero_when_negative_edge():
    assert kelly_fraction(0.40, 2.10) == 0.0


def test_kelly_at_extreme():
    assert kelly_fraction(1.0, 2.0) == 1.0
    assert kelly_fraction(0.0, 2.0) == 0.0


def test_kelly_invalid_odds():
    assert kelly_fraction(0.6, 1.0) == 0.0
    assert kelly_fraction(0.6, 0.5) == 0.0


def test_break_even_basic():
    assert break_even_probability(2.0) == 0.5
    assert math.isclose(break_even_probability(4.0), 0.25)
    assert break_even_probability(1.0) == 1.0


def test_expected_value_correct_sign():
    assert expected_value_percent(0.55, 2.10) > 0
    assert expected_value_percent(0.40, 2.10) < 0


def test_recommendation_stake_amounts():
    rec = recommend_stake(0.55, 2.10)
    bankroll = 1000.0
    assert rec.stake_full(bankroll) > rec.stake_half(bankroll) > rec.stake_quarter(bankroll)


def test_recommendation_flat_zero_when_negative():
    rec = recommend_stake(0.40, 2.10)
    assert rec.flat_fraction == 0.0
    assert rec.stake_flat(1000.0) == 0.0


def test_recommendation_flat_positive_when_positive_ev():
    rec = recommend_stake(0.60, 2.20)
    assert rec.flat_fraction > 0
