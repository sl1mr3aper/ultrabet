"""Индекс «моментума» — насколько команда в восходящем/нисходящем тренде.

Берётся скользящая средняя результатов с экспоненциальным затуханием. Возвращает
число в диапазоне [-1.0, +1.0]:
- > +0.3 — заметный апсайд
- |x| <= 0.1 — ровный график
- < -0.3 — заметный спад
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MomentumReading:
    value: float
    label: str

    @property
    def emoji(self) -> str:
        if self.value > 0.3:
            return "📈"
        if self.value < -0.3:
            return "📉"
        return "➡️"


def compute_momentum(outcomes: list[str], *, decay: float = 0.7) -> MomentumReading:
    """outcomes — последовательность 'W'/'D'/'L', где элемент 0 — самый новый."""
    if not outcomes:
        return MomentumReading(0.0, "—")
    score = 0.0
    weight_total = 0.0
    weight = 1.0
    for o in outcomes:
        if o == "W":
            score += weight * 1.0
        elif o == "L":
            score += weight * -1.0
        weight_total += weight
        weight *= decay
    if weight_total == 0:
        return MomentumReading(0.0, "ровно")
    value = score / weight_total
    if value > 0.3:
        label = "восходящий"
    elif value < -0.3:
        label = "нисходящий"
    else:
        label = "ровный"
    return MomentumReading(value, label)


__all__ = ["MomentumReading", "compute_momentum"]
