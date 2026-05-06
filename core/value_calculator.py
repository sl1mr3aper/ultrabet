"""Поиск EV-ставок по соотношению вероятность × коэфф.

Честный коэффициент = 1 / вероятность.
EV = (вероятность × коэфф - 1) × 100%.
Критерий Келли = (b*p - q) / b, где b = коэфф - 1, p = вер-ть, q = 1-p.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ValueBet:
    market_key: str
    probability: float
    actual_odds: float
    fair_odds: float       # честный коэфф = 1 / probability
    value_percent: float   # EV в %
    is_value: bool
    kelly_fraction: float = 0.0      # доля Келли (0..1)
    half_kelly_fraction: float = 0.0  # пол-Келли


def _kelly_fraction(prob: float, odds: float) -> float:
    """Доля Келли: f* = (b*p - q) / b."""
    if odds <= 1.0 or prob <= 0.0 or prob >= 1.0:
        return 0.0
    b = odds - 1.0
    p = prob
    q = 1.0 - p
    f = (b * p - q) / b
    return max(f, 0.0)


class ValueCalculator:
    """Расчёт EV: честный_кф = 1/p, EV = p*кф - 1."""

    def __init__(
        self,
        *,
        min_odds: float = 1.51,
        min_value_percent: float = 2.0,
        min_probability: float = 0.35,
    ) -> None:
        self.min_odds = max(1.01, min_odds)
        self.min_value_percent = max(0.0, min_value_percent)
        self.min_probability = max(0.0, min(1.0, min_probability))

    def calculate(self, *, probability: float, actual_odds: float, market_key: str = "") -> ValueBet:
        prob = max(0.0, min(1.0, probability))
        odds = max(0.0, actual_odds)
        if prob <= 0 or odds <= 0:
            return ValueBet(market_key, prob, odds, 0.0, -100.0, False, 0.0, 0.0)
        # Честный коэффициент
        fair = 1.0 / prob
        # EV
        value_percent = (prob * odds - 1.0) * 100.0
        # Келли
        kelly = _kelly_fraction(prob, odds)
        half_kelly = kelly * 0.5
        # Проверки
        suspicious = prob >= 0.90 and odds > 2.0
        is_value = (
            not suspicious
            and odds > self.min_odds
            and value_percent >= self.min_value_percent
            and prob >= self.min_probability
        )
        return ValueBet(
            market_key, prob, odds, fair, value_percent, is_value,
            kelly_fraction=kelly, half_kelly_fraction=half_kelly,
        )

    def find_top_value(
        self,
        probabilities: dict[str, float],
        odds_map: dict[str, float],
        *,
        top_n: int = 15,
    ) -> list[ValueBet]:
        results: list[ValueBet] = []
        for key, prob in probabilities.items():
            odds = odds_map.get(key)
            if not odds or odds <= 1.0:
                continue
            bet = self.calculate(probability=prob, actual_odds=odds, market_key=key)
            if bet.is_value:
                results.append(bet)
        results.sort(key=lambda b: b.value_percent, reverse=True)
        return results[:top_n]


__all__ = ["ValueBet", "ValueCalculator"]
