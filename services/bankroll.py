"""Bankroll / staking стратегии.

Реализовано:
- flat: всегда ставим фиксированную долю банка.
- kelly: доля Келли f* = (b*p - q) / b, где b = odds - 1, p = prob, q = 1 - p.
- fractional_kelly: 0.5 × Kelly — безопаснее.
- martingale: удваиваем после каждого проигрыша (не рекомендуется, но бывает).
- anti_martingale: удваиваем после каждого выигрыша (pyramiding).
- percent: фиксированный процент банка, не зависит от валуйности.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StakeKind(str, Enum):
    FLAT = "flat"
    KELLY = "kelly"
    HALF_KELLY = "half_kelly"
    QUARTER_KELLY = "quarter_kelly"
    PERCENT = "percent"
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"


@dataclass(slots=True)
class StakeInput:
    bankroll: float
    probability: float  # наша оценка
    odds: float
    base_percent: float = 1.0  # база для flat/percent (в % от банка)
    previous_losses: int = 0  # для martingale
    previous_wins: int = 0  # для anti_martingale
    max_fraction: float = 0.10  # cap 10% банка


def _kelly_fraction(probability: float, odds: float) -> float:
    if odds <= 1.0 or probability <= 0.0:
        return 0.0
    b = odds - 1.0
    p = probability
    q = 1.0 - p
    f = (b * p - q) / b
    return max(f, 0.0)


def compute_stake(si: StakeInput, kind: StakeKind) -> float:
    """Возвращает размер ставки в валюте банка."""
    if si.bankroll <= 0:
        return 0.0
    base = si.bankroll * (si.base_percent / 100.0)
    if kind is StakeKind.FLAT or kind is StakeKind.PERCENT:
        fraction = si.base_percent / 100.0
    elif kind is StakeKind.KELLY:
        fraction = _kelly_fraction(si.probability, si.odds)
    elif kind is StakeKind.HALF_KELLY:
        fraction = _kelly_fraction(si.probability, si.odds) * 0.5
    elif kind is StakeKind.QUARTER_KELLY:
        fraction = _kelly_fraction(si.probability, si.odds) * 0.25
    elif kind is StakeKind.MARTINGALE:
        fraction = (si.base_percent / 100.0) * (2 ** si.previous_losses)
    elif kind is StakeKind.ANTI_MARTINGALE:
        fraction = (si.base_percent / 100.0) * (2 ** si.previous_wins)
    else:
        fraction = si.base_percent / 100.0
    fraction = max(0.0, min(fraction, si.max_fraction))
    if kind is StakeKind.FLAT:
        return base  # fixed
    return si.bankroll * fraction


def describe(kind: StakeKind) -> str:
    return {
        StakeKind.FLAT: "Всегда одинаковая ставка (безопасно).",
        StakeKind.KELLY: "Полный Kelly — математически оптимален, но большая волатильность.",
        StakeKind.HALF_KELLY: "Половина Kelly — более щадящий вариант.",
        StakeKind.QUARTER_KELLY: "Четверть Kelly — самый осторожный Kelly.",
        StakeKind.PERCENT: "Фиксированный % от банка.",
        StakeKind.MARTINGALE: "После проигрыша удваиваем — опасно.",
        StakeKind.ANTI_MARTINGALE: "После выигрыша удваиваем — пирамиды.",
    }[kind]


__all__ = ["StakeInput", "StakeKind", "compute_stake", "describe"]
