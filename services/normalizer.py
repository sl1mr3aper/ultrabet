"""Нормализация вероятностей и коэффициентов.

Используется:
- привести "implied" вероятности из коэфов к сумме 1.0 (удалить маржу букмекера).
- сгладить аномальные коэфы (outlier cap).
- конвертировать между decimal / american / fractional форматами.
"""

from __future__ import annotations

from fractions import Fraction


def implied_from_odds(odds: float) -> float:
    """Вероятность, подразумеваемая коэффициентом (с учётом маржи)."""
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def strip_margin(probs: list[float]) -> list[float]:
    """Убирает маржу, нормализуя probs к сумме 1.0."""
    total = sum(probs)
    if total <= 0:
        return [0.0] * len(probs)
    return [p / total for p in probs]


def fair_odds_from_probs(probs: list[float]) -> list[float]:
    """Fair odds = 1 / p (без маржи)."""
    return [1.0 / p if p > 0 else float("inf") for p in probs]


def margin_percent(probs_implied: list[float]) -> float:
    """Маржа букмекера в % (сумма implied - 100%)."""
    total = sum(probs_implied) * 100.0
    return total - 100.0


def decimal_to_american(decimal_odds: float) -> int:
    """Decimal → американский формат (+200, -150)."""
    if decimal_odds <= 1.0:
        return 0
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100))
    return -int(round(100.0 / (decimal_odds - 1.0)))


def american_to_decimal(american: int) -> float:
    """Американский → decimal."""
    if american > 0:
        return 1.0 + american / 100.0
    if american < 0:
        return 1.0 + 100.0 / abs(american)
    return 1.0


def decimal_to_fractional(decimal_odds: float, *, max_denom: int = 100) -> str:
    """Decimal → строка формата "5/2"."""
    if decimal_odds <= 1.0:
        return "0/1"
    frac = Fraction(decimal_odds - 1.0).limit_denominator(max_denom)
    return f"{frac.numerator}/{frac.denominator}"


def fractional_to_decimal(fractional: str) -> float:
    """Строка "5/2" → decimal."""
    parts = fractional.split("/")
    if len(parts) != 2:
        return 0.0
    try:
        num = float(parts[0])
        den = float(parts[1])
        if den == 0:
            return 0.0
        return 1.0 + num / den
    except ValueError:
        return 0.0


def clamp_probability(p: float, *, min_p: float = 0.005, max_p: float = 0.995) -> float:
    """Обрезает вероятность в разумные границы."""
    return max(min_p, min(max_p, p))


__all__ = [
    "american_to_decimal",
    "clamp_probability",
    "decimal_to_american",
    "decimal_to_fractional",
    "fair_odds_from_probs",
    "fractional_to_decimal",
    "implied_from_odds",
    "margin_percent",
    "strip_margin",
]
