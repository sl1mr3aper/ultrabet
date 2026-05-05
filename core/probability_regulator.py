"""Probability Regulator — ядро коррекции вероятностей по истории.

Идея: модель даёт ансамблевую вероятность (например, ТБ 2.5 = 57%),
но реальный hit-rate этого рынка по последним N матчам этой лиги может
быть существенно выше или ниже. Регулятор смешивает (Bayesian blend)
prior модели с фактическим historical hit-rate'ом и пересортировывает
ТОП-15 по итоговой вероятности.

Дополнительно учитываем:
* hit-rate из `prediction_outcomes` (наша обратная связь по уже
  завершённым прогнозам того же `market_key` — кросс-лига).
* expected value (prob × odd) — рынки с лучшим EV получают приоритет.

Формула:
    p_hist = hits / games  (Beta-сглаживание: hits+1, games+2)
    weight_hist = min(1.0, games / 50)     # доверие растёт с объёмом
    p_combined = (1 - w) * p_model + w * p_hist
    confidence = p_combined  # для сортировки используем именно его

Модуль — pure-функции, никаких сайд-эффектов; принимает на вход уже
загруженные out of БД rows.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from core.market_evaluator import evaluate_market


@dataclass(slots=True)
class HistoricalRow:
    """Один матч из истории — только то, что нужно регулятору."""
    home_score: int
    away_score: int


@dataclass(slots=True)
class RegulationResult:
    market_key: str
    p_model: float
    p_corrected: float
    hist_hits: int
    hist_games: int
    delta_pp: float  # сдвиг в процентных пунктах (+/-)


def _beta_rate(hits: int, games: int) -> float:
    """Сглаженная частота через прибавку Бета(1,1)."""
    return (hits + 1) / (games + 2)


def _league_hitrate(
    market_key: str, history: Iterable[HistoricalRow],
) -> tuple[int, int]:
    hits = 0
    games = 0
    for r in history:
        if r.home_score is None or r.away_score is None:
            continue
        outcome = evaluate_market(market_key, r.home_score, r.away_score)
        if outcome is None:
            continue
        games += 1
        if outcome:
            hits += 1
    return hits, games


# Минимальное количество семплов для статзначимой коррекции.
# При меньшем количестве регулятор добавляет шум, а не сигнал.
MIN_SAMPLES_HIST = 30
MIN_SAMPLES_FEEDBACK = 20


def regulate(
    model_probs: dict[str, float],
    history: list[HistoricalRow],
    *,
    feedback_hitrates: dict[str, tuple[int, int]] | None = None,
    history_weight_cap: float = 0.35,
    feedback_weight_cap: float = 0.20,
    history_max_n: int = 100,
    feedback_max_n: int = 60,
) -> dict[str, RegulationResult]:
    """Возвращает {market_key: RegulationResult}.

    Параметры:
        model_probs: исходные вероятности от ансамбля, {key: prob}.
        history: последние N матчей в лиге (home_score, away_score).
        feedback_hitrates: уже посчитанный (hits, games) per market_key
            из prediction_outcomes (полностью завершённые прогнозы).
        history_weight_cap: максимальный вес исторического префикса
            (0.45 = модель имеет минимум 55% веса).
        feedback_weight_cap: максимальный вес обратной связи.
    """
    feedback = feedback_hitrates or {}

    # Сначала кэшируем hit-rate по лиге для всех уникальных ключей.
    league_cache: dict[str, tuple[int, int]] = {}

    out: dict[str, RegulationResult] = {}
    for key, p_model in model_probs.items():
        # 1) История лиги
        if key not in league_cache:
            league_cache[key] = _league_hitrate(key, history)
        h_hits, h_games = league_cache[key]
        if h_games >= MIN_SAMPLES_HIST:
            p_hist = _beta_rate(h_hits, h_games)
            w_hist = min(history_weight_cap, h_games / float(history_max_n))
        else:
            p_hist = p_model
            w_hist = 0.0

        # 2) Обратная связь (наши прошлые прогнозы того же рынка)
        f_hits, f_games = feedback.get(key, (0, 0))
        if f_games >= MIN_SAMPLES_FEEDBACK:
            p_feedback = _beta_rate(f_hits, f_games)
            w_feedback = min(feedback_weight_cap, f_games / float(feedback_max_n))
        else:
            p_feedback = p_model
            w_feedback = 0.0

        w_model = 1.0 - w_hist - w_feedback
        # Гарантируем неотрицательность при перекрытии cap'ов.
        w_model = max(w_model, 0.0)

        p_corrected = (
            w_model * p_model + w_hist * p_hist + w_feedback * p_feedback
        )
        # Не выпускаем за [0, 1].
        p_corrected = max(0.001, min(0.999, p_corrected))

        out[key] = RegulationResult(
            market_key=key,
            p_model=p_model,
            p_corrected=p_corrected,
            hist_hits=h_hits,
            hist_games=h_games,
            delta_pp=(p_corrected - p_model) * 100.0,
        )
    return out


def aggregate_feedback(
    rows: Iterable[tuple[str, bool | None]],
) -> dict[str, tuple[int, int]]:
    """Превращает поток (market_key, hit) в {key: (hits, games)}.

    Записи с hit=None (исход неизвестен) — игнорируем.
    """
    bucket: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [hits, games]
    for key, hit in rows:
        if hit is None or not key:
            continue
        bucket[key][1] += 1
        if hit:
            bucket[key][0] += 1
    return {k: (v[0], v[1]) for k, v in bucket.items()}


__all__ = [
    "HistoricalRow",
    "RegulationResult",
    "aggregate_feedback",
    "regulate",
]
