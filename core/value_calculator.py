"""Поиск valuable bets по соотношению вероятность × коэф."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ValueBet:
    market_key: str
    probability: float
    actual_odds: float
    fair_odds: float
    value_percent: float
    is_value: bool


class ValueCalculator:
    """value = prob * actual_odds - 1; fair_odds = 1 / prob."""

    def __init__(self, *, min_odds: float = 1.20, min_value_percent: float = 2.0) -> None:
        self.min_odds = max(1.01, min_odds)
        self.min_value_percent = max(0.0, min_value_percent)

    def calculate(self, *, probability: float, actual_odds: float, market_key: str = "") -> ValueBet:
        prob = max(0.0, min(1.0, probability))
        odds = max(0.0, actual_odds)
        if prob <= 0 or odds <= 0:
            return ValueBet(market_key, prob, odds, 0.0, -100.0, False)
        fair = 1.0 / prob
        value_percent = (prob * odds - 1.0) * 100.0
        is_value = (
            odds >= self.min_odds
            and value_percent >= self.min_value_percent
            and prob >= 0.10
        )
        return ValueBet(market_key, prob, odds, fair, value_percent, is_value)

    def find_top_value(
        self,
        probabilities: dict[str, float],
        odds_map: dict[str, float],
        *,
        top_n: int = 5,
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
