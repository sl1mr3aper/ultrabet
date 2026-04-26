"""Различные стратегии выбора ставок.

Разные игроки хотят разный риск-профиль:
- conservative: ставки с ~hi вероятностью, низким value%
- balanced: средний value% и средний коэф
- aggressive: большой value% + большой коэф + низкая вероятность
- combo: только underdogs с очень большой валуйностью
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.value_calculator import ValueBet


class StrategyKind(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    UNDERDOG = "underdog"


@dataclass(slots=True)
class StrategyFilter:
    min_probability: float = 0.0
    max_probability: float = 1.0
    min_odds: float = 1.01
    max_odds: float = 100.0
    min_value_pct: float = 0.0
    max_value_pct: float = 10000.0
    top_n: int = 5

    def apply(self, bets: list[ValueBet]) -> list[ValueBet]:
        filtered = [
            b
            for b in bets
            if self.min_probability <= b.probability <= self.max_probability
            and self.min_odds <= b.actual_odds <= self.max_odds
            and self.min_value_pct <= b.value_percent <= self.max_value_pct
        ]
        filtered.sort(key=lambda b: b.value_percent, reverse=True)
        return filtered[: self.top_n]


STRATEGIES: dict[StrategyKind, StrategyFilter] = {
    StrategyKind.CONSERVATIVE: StrategyFilter(
        min_probability=0.55,
        min_odds=1.25,
        max_odds=2.20,
        min_value_pct=2.0,
        top_n=5,
    ),
    StrategyKind.BALANCED: StrategyFilter(
        min_probability=0.35,
        min_odds=1.50,
        max_odds=4.50,
        min_value_pct=5.0,
        top_n=5,
    ),
    StrategyKind.AGGRESSIVE: StrategyFilter(
        min_probability=0.18,
        min_odds=3.00,
        max_odds=15.0,
        min_value_pct=8.0,
        top_n=5,
    ),
    StrategyKind.UNDERDOG: StrategyFilter(
        min_probability=0.10,
        min_odds=4.00,
        max_odds=30.0,
        min_value_pct=15.0,
        top_n=3,
    ),
}


def apply_strategy(bets: list[ValueBet], kind: StrategyKind) -> list[ValueBet]:
    """Применить именованную стратегию к списку ставок."""
    flt = STRATEGIES.get(kind, STRATEGIES[StrategyKind.BALANCED])
    return flt.apply(bets)


def describe_strategy(kind: StrategyKind) -> str:
    """Короткое описание стратегии для UI."""
    descriptions = {
        StrategyKind.CONSERVATIVE: (
            "🛡 Консервативно — большие вероятности, небольшие коэф, "
            "минимум риска."
        ),
        StrategyKind.BALANCED: (
            "⚖️ Сбалансированно — средние коэф и валуйность, универсальная "
            "стратегия."
        ),
        StrategyKind.AGGRESSIVE: (
            "🔥 Агрессивно — большие коэф, высокая валуйность, больший "
            "дисперсия."
        ),
        StrategyKind.UNDERDOG: (
            "🎯 На аутсайдеров — только самые жирные коэф с очень большой EV."
        ),
    }
    return descriptions.get(kind, "")


__all__ = [
    "STRATEGIES",
    "StrategyFilter",
    "StrategyKind",
    "apply_strategy",
    "describe_strategy",
]
