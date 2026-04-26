"""Тесты стратегий выбора ставок."""

from __future__ import annotations

from core.value_calculator import ValueBet
from services.strategy import (
    STRATEGIES,
    StrategyFilter,
    StrategyKind,
    apply_strategy,
    describe_strategy,
)


def _bet(prob: float, odds: float, value: float) -> ValueBet:
    return ValueBet(
        market_key=f"m_{prob}_{odds}",
        probability=prob,
        actual_odds=odds,
        fair_odds=1 / prob if prob > 0 else 0,
        value_percent=value,
        is_value=True,
    )


def test_conservative_filter_keeps_safe_bets():
    bets = [
        _bet(0.70, 1.50, 4.0),  # safe
        _bet(0.30, 4.0, 15.0),  # aggressive, excluded
    ]
    out = apply_strategy(bets, StrategyKind.CONSERVATIVE)
    assert len(out) == 1
    assert out[0].probability == 0.70


def test_aggressive_filter_picks_bold():
    bets = [
        _bet(0.20, 5.0, 10.0),  # aggressive OK
        _bet(0.75, 1.4, 2.0),  # safe, excluded
    ]
    out = apply_strategy(bets, StrategyKind.AGGRESSIVE)
    assert len(out) == 1
    assert out[0].actual_odds == 5.0


def test_underdog_filter_restrictive():
    bets = [
        _bet(0.12, 7.0, 20.0),
        _bet(0.22, 4.5, 12.0),  # value < 15, excluded
    ]
    out = apply_strategy(bets, StrategyKind.UNDERDOG)
    assert len(out) == 1


def test_top_n_respected():
    bets = [_bet(0.40, 2.0, 5.0 + i) for i in range(10)]
    out = apply_strategy(bets, StrategyKind.BALANCED)
    assert len(out) <= 5


def test_all_strategies_defined():
    for k in StrategyKind:
        assert k in STRATEGIES
        assert isinstance(describe_strategy(k), str)


def test_custom_filter():
    flt = StrategyFilter(min_odds=2.0, max_odds=3.0, top_n=2)
    bets = [
        _bet(0.4, 2.5, 10.0),
        _bet(0.3, 1.8, 15.0),  # excluded by min_odds
        _bet(0.2, 2.8, 8.0),
    ]
    out = flt.apply(bets)
    assert len(out) == 2
    for b in out:
        assert 2.0 <= b.actual_odds <= 3.0
