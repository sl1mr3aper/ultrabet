"""Парлейный (экспресс) калькулятор.

Считает итоговый коэф, итоговую вероятность, EV и риск-метрики для набора
независимых ставок.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import prod


@dataclass(slots=True)
class ParlayLeg:
    name: str
    probability: float  # наша оценка 0..1
    odds: float  # фактический коэф


@dataclass(slots=True)
class ParlayResult:
    total_odds: float
    combined_probability: float
    fair_total_odds: float
    value_percent: float
    expected_return: float  # на 1 ставку
    leg_count: int


def calculate_parlay(legs: list[ParlayLeg]) -> ParlayResult | None:
    """Возвращает None для пустого или некорректного ввода."""
    if not legs:
        return None
    for leg in legs:
        if leg.odds <= 1.0 or not (0.0 < leg.probability <= 1.0):
            return None
    total_odds = prod(leg.odds for leg in legs)
    combined_prob = prod(leg.probability for leg in legs)
    fair = 1.0 / combined_prob if combined_prob > 0 else float("inf")
    value_pct = (combined_prob * total_odds - 1.0) * 100.0
    ev = combined_prob * total_odds - 1.0
    return ParlayResult(
        total_odds=total_odds,
        combined_probability=combined_prob,
        fair_total_odds=fair,
        value_percent=value_pct,
        expected_return=ev,
        leg_count=len(legs),
    )


def describe_risk(result: ParlayResult) -> str:
    """Назначает риск-уровень в зависимости от total_odds."""
    if result.total_odds < 2.0:
        return "🟢 низкий"
    if result.total_odds < 5.0:
        return "🟡 умеренный"
    if result.total_odds < 15.0:
        return "🟠 высокий"
    if result.total_odds < 50.0:
        return "🔴 очень высокий"
    return "💀 экстремальный"


__all__ = ["ParlayLeg", "ParlayResult", "calculate_parlay", "describe_risk"]
