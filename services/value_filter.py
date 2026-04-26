"""Фильтры для value bets: по probability, odds, value%, market type.

Позволяет собрать конвейер: базовый список ставок → фильтрация по
стратегии → сортировка → пагинация.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ValueBet:
    """Общий контракт для value-bet в value_filter."""

    game_id: int
    game_label: str
    market: str
    bookmaker: str
    probability: float
    odds: float
    fair_odds: float
    value_percent: float
    league: str = ""
    starts_at: str = ""


Filter = Callable[[ValueBet], bool]


def min_probability(threshold: float) -> Filter:
    return lambda b: b.probability >= threshold


def max_probability(threshold: float) -> Filter:
    return lambda b: b.probability <= threshold


def odds_range(low: float, high: float) -> Filter:
    return lambda b: low <= b.odds <= high


def min_value_percent(threshold: float) -> Filter:
    return lambda b: b.value_percent >= threshold


def only_markets(*markets: str) -> Filter:
    allowed = frozenset(markets)
    return lambda b: b.market in allowed


def exclude_markets(*markets: str) -> Filter:
    forbidden = frozenset(markets)
    return lambda b: b.market not in forbidden


def only_bookmakers(*names: str) -> Filter:
    allowed = frozenset(names)
    return lambda b: b.bookmaker in allowed


def only_leagues(*leagues: str) -> Filter:
    allowed = frozenset(leagues)
    return lambda b: b.league in allowed


def exclude_leagues(*leagues: str) -> Filter:
    forbidden = frozenset(leagues)
    return lambda b: b.league not in forbidden


def compose(*filters: Filter) -> Filter:
    def combined(b: ValueBet) -> bool:
        return all(f(b) for f in filters)
    return combined


def apply_filters(bets: list[ValueBet], filters: list[Filter]) -> list[ValueBet]:
    if not filters:
        return list(bets)
    combined = compose(*filters)
    return [b for b in bets if combined(b)]


def sort_by_value_desc(bets: list[ValueBet]) -> list[ValueBet]:
    return sorted(bets, key=lambda b: b.value_percent, reverse=True)


def sort_by_odds_asc(bets: list[ValueBet]) -> list[ValueBet]:
    return sorted(bets, key=lambda b: b.odds)


def sort_by_probability_desc(bets: list[ValueBet]) -> list[ValueBet]:
    return sorted(bets, key=lambda b: b.probability, reverse=True)


def top_n(bets: list[ValueBet], n: int) -> list[ValueBet]:
    return bets[:n]


def pipeline(
    bets: list[ValueBet],
    *,
    filters: list[Filter] | None = None,
    sort_fn: Callable[[list[ValueBet]], list[ValueBet]] = sort_by_value_desc,
    limit: int | None = None,
) -> list[ValueBet]:
    result = apply_filters(bets, filters or [])
    result = sort_fn(result)
    if limit is not None:
        result = top_n(result, limit)
    return result


def to_dict_list(bets: list[ValueBet]) -> list[dict[str, Any]]:
    return [
        {
            "game_id": b.game_id,
            "game_label": b.game_label,
            "market": b.market,
            "bookmaker": b.bookmaker,
            "probability": round(b.probability, 4),
            "odds": round(b.odds, 2),
            "fair_odds": round(b.fair_odds, 2),
            "value_percent": round(b.value_percent, 2),
            "league": b.league,
        }
        for b in bets
    ]


__all__ = [
    "Filter",
    "ValueBet",
    "apply_filters",
    "compose",
    "exclude_leagues",
    "exclude_markets",
    "max_probability",
    "min_probability",
    "min_value_percent",
    "odds_range",
    "only_bookmakers",
    "only_leagues",
    "only_markets",
    "pipeline",
    "sort_by_odds_asc",
    "sort_by_probability_desc",
    "sort_by_value_desc",
    "to_dict_list",
    "top_n",
]
