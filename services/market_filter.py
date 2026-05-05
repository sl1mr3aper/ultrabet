"""Market filter — блокирует «брать» для рынков с плохим историческим CLV.

После анализа исторических CSV видно, что некоторые рынки систематически
проигрывают модели даже при положительной EV — это признак того, что
наша вероятность на этом рынке систематически смещена. Например, ОЗ-Yes
для лиг с низкой результативностью почти всегда переоценивается из-за
независимости голов в Пуассоне.

Фильтр работает по правилу:
* Берём `market_hit_rates` из `LearningSnapshot` (на >= MIN_SAMPLES_BLOCK).
* Сравниваем эмпирический hit-rate с break-even (1/odds).
* Если CLV (эмпирическая - модельная) систематически отрицательная и
  выборка большая (>=30) — кладём `market_key` в блок-лист «не брать».

Не вмешиваемся в обычную сортировку ТОПа — фильтр отрабатывает только
на финальном вердикте «брать»: пик с заблокированного рынка не получит
verdict="брать", независимо от EV.
"""

from __future__ import annotations

# Минимум семплов для статзначимого блока.
MIN_SAMPLES_BLOCK = 30
# Если эмпирическая частота на 12+ pp ниже модельной — рынок систематически
# переоценен → блокируем как «брать».
NEGATIVE_DELTA_PP_THRESHOLD = 0.12


class MarketFilter:
    """Блокирует «брать» для рынков с систематически отрицательным CLV.

    Использование:
        filter = MarketFilter(snapshot=self_learner.latest)
        if filter.is_blocked(market_key, model_prob):
            verdict = "не брать"
    """

    def __init__(
        self,
        *,
        market_hit_rates: dict[str, tuple[int, int]] | None = None,
        min_samples: int = MIN_SAMPLES_BLOCK,
        delta_threshold: float = NEGATIVE_DELTA_PP_THRESHOLD,
    ) -> None:
        self._rates = market_hit_rates or {}
        self._min_samples = min_samples
        self._delta_threshold = delta_threshold

    def is_blocked(self, market_key: str, model_prob: float) -> bool:
        """True если рынок систематически переоценен и нет смысла «брать»."""
        rate = self._rates.get(market_key)
        if rate is None:
            return False
        hits, games = rate
        if games < self._min_samples or games <= 0:
            return False
        empirical = hits / games
        # Если модель в среднем ставит p=0.65, а реально сыгрывает 0.45 —
        # это 20pp gap, систематический миска́либрейт. Блокируем.
        return (model_prob - empirical) >= self._delta_threshold

    def empirical_rate(self, market_key: str) -> float | None:
        """Возвращает эмпирический hit-rate если есть достаточно данных."""
        rate = self._rates.get(market_key)
        if rate is None:
            return None
        hits, games = rate
        if games < self._min_samples:
            return None
        return hits / games


__all__ = ["MIN_SAMPLES_BLOCK", "NEGATIVE_DELTA_PP_THRESHOLD", "MarketFilter"]
