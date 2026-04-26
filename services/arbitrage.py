"""Поиск арбитражных ситуаций (surebets) между букмекерами.

Для 2-way (e.g. теннис home/away): arbitrage, если 1/o1 + 1/o2 < 1.
Для 3-way (1x2): 1/oH + 1/oD + 1/oA < 1.

Возвращает процент прибыли и оптимальное распределение банкролла.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArbCheck:
    is_arb: bool
    margin: float  # <1 означает арб, например 0.97 → 3% прибыль
    profit_percent: float  # ((1/margin) - 1) * 100
    bookmaker_per_outcome: dict[str, str]  # ключ → название букмекера
    allocation: dict[str, float]  # доля от 1.0 на каждый исход


def _margin(odds: list[float]) -> float:
    return sum(1.0 / o for o in odds if o > 0)


def find_arb_2way(
    odd_a: float,
    odd_b: float,
    *,
    book_a: str = "?",
    book_b: str = "?",
) -> ArbCheck:
    m = _margin([odd_a, odd_b])
    is_arb = m < 1.0 and odd_a > 1.0 and odd_b > 1.0
    alloc = {}
    if is_arb:
        alloc = {
            "a": (1.0 / odd_a) / m,
            "b": (1.0 / odd_b) / m,
        }
    return ArbCheck(
        is_arb=is_arb,
        margin=m,
        profit_percent=max(0.0, (1.0 / m - 1.0) * 100.0) if is_arb else 0.0,
        bookmaker_per_outcome={"a": book_a, "b": book_b},
        allocation=alloc,
    )


def find_arb_3way(
    odd_home: float,
    odd_draw: float,
    odd_away: float,
    *,
    book_home: str = "?",
    book_draw: str = "?",
    book_away: str = "?",
) -> ArbCheck:
    m = _margin([odd_home, odd_draw, odd_away])
    is_arb = (
        m < 1.0
        and odd_home > 1.0
        and odd_draw > 1.0
        and odd_away > 1.0
    )
    alloc = {}
    if is_arb:
        alloc = {
            "home": (1.0 / odd_home) / m,
            "draw": (1.0 / odd_draw) / m,
            "away": (1.0 / odd_away) / m,
        }
    return ArbCheck(
        is_arb=is_arb,
        margin=m,
        profit_percent=max(0.0, (1.0 / m - 1.0) * 100.0) if is_arb else 0.0,
        bookmaker_per_outcome={
            "home": book_home,
            "draw": book_draw,
            "away": book_away,
        },
        allocation=alloc,
    )


def optimal_stakes(total: float, arb: ArbCheck) -> dict[str, float]:
    """Распределить total по исходам в пропорции arbitrage, округление до 0.01."""
    return {k: round(total * v, 2) for k, v in arb.allocation.items()}


__all__ = ["ArbCheck", "find_arb_2way", "find_arb_3way", "optimal_stakes"]
