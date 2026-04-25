"""Калькулятор стейка по Kelly criterion и фиксированной банкролл-стратегии.

Используется в `/calculator` команде, чтобы пользователь мог быстро прикинуть
оптимальный размер ставки исходя из своих параметров.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StakeRecommendation:
    full_kelly_fraction: float
    half_kelly_fraction: float
    quarter_kelly_fraction: float
    flat_fraction: float
    expected_value_pct: float

    def stake_full(self, bankroll: float) -> float:
        return max(0.0, self.full_kelly_fraction * bankroll)

    def stake_half(self, bankroll: float) -> float:
        return max(0.0, self.half_kelly_fraction * bankroll)

    def stake_quarter(self, bankroll: float) -> float:
        return max(0.0, self.quarter_kelly_fraction * bankroll)

    def stake_flat(self, bankroll: float) -> float:
        return max(0.0, self.flat_fraction * bankroll)


def kelly_fraction(probability: float, decimal_odds: float) -> float:
    """Классический Kelly criterion для бинарной ставки.

    f* = (b·p - q) / b, где b = decimal_odds-1, q = 1-p.
    Возвращает 0 если ожидание неположительное.
    """
    if decimal_odds <= 1.0:
        return 0.0
    p = max(0.0, min(1.0, probability))
    q = 1.0 - p
    b = decimal_odds - 1.0
    f = (b * p - q) / b
    return max(0.0, min(1.0, f))


def expected_value_percent(probability: float, decimal_odds: float) -> float:
    """EV в процентах: (p * (odds-1) - (1-p)) * 100."""
    p = max(0.0, min(1.0, probability))
    return (p * (decimal_odds - 1.0) - (1.0 - p)) * 100.0


def recommend_stake(
    probability: float,
    decimal_odds: float,
    *,
    flat_fraction: float = 0.02,
) -> StakeRecommendation:
    """Полный набор рекомендаций по размеру ставки."""
    full = kelly_fraction(probability, decimal_odds)
    return StakeRecommendation(
        full_kelly_fraction=full,
        half_kelly_fraction=full / 2,
        quarter_kelly_fraction=full / 4,
        flat_fraction=flat_fraction if expected_value_percent(probability, decimal_odds) > 0 else 0.0,
        expected_value_pct=expected_value_percent(probability, decimal_odds),
    )


def break_even_probability(decimal_odds: float) -> float:
    """Минимальная вероятность, при которой ставка безубыточна."""
    if decimal_odds <= 1.0:
        return 1.0
    return 1.0 / decimal_odds


__all__ = [
    "StakeRecommendation",
    "break_even_probability",
    "expected_value_percent",
    "kelly_fraction",
    "recommend_stake",
]
