"""Тесты поиска арбов."""

from __future__ import annotations

from services.arbitrage import find_arb_2way, find_arb_3way, optimal_stakes


def test_no_arb_2way():
    r = find_arb_2way(1.8, 2.0)
    assert r.is_arb is False


def test_arb_2way_positive():
    # 2.1 + 2.1 → 1/2.1 + 1/2.1 = 0.952 < 1 → арб
    r = find_arb_2way(2.1, 2.1)
    assert r.is_arb is True
    assert r.profit_percent > 0
    assert abs(sum(r.allocation.values()) - 1.0) < 1e-6


def test_arb_3way_negative():
    r = find_arb_3way(2.0, 3.0, 3.5)  # margin > 1
    assert r.is_arb is False


def test_arb_3way_positive():
    r = find_arb_3way(2.5, 3.6, 3.6)
    assert r.is_arb is True
    assert r.profit_percent > 0


def test_optimal_stakes_sums_to_total():
    r = find_arb_2way(2.1, 2.1)
    stakes = optimal_stakes(100.0, r)
    assert abs(sum(stakes.values()) - 100.0) < 0.05


def test_zero_or_invalid_odds_no_arb():
    assert find_arb_2way(0.5, 2.0).is_arb is False
    assert find_arb_2way(1.0, 1.0).is_arb is False
