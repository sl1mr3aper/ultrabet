"""Monte-Carlo симуляция матчей.

По заданным home_xg/away_xg выполняет N симуляций с Poisson-распределением
голов. Для каждой симуляции определяет исход и агрегирует вероятности.

Даёт дополнительную "второй взгляд" оценку к аналитическим Poisson и Glicko.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.poisson_model import poisson_match_probs


@dataclass(slots=True)
class SimulationResult:
    n_runs: int
    home_win_pct: float
    draw_pct: float
    away_win_pct: float
    btts_pct: float
    over_2_5_pct: float
    over_1_5_pct: float
    under_2_5_pct: float
    avg_total_goals: float
    avg_home_goals: float
    avg_away_goals: float
    score_distribution: dict[str, float]  # "H:A" → %


def simulate(
    home_xg: float,
    away_xg: float,
    *,
    n_runs: int = 5000,
    max_goals: int = 10,
    seed: int | None = None,
) -> SimulationResult:
    if seed is not None:
        random.seed(seed)
    if n_runs <= 0:
        n_runs = 1

    # Предпосчитаем Poisson CDF для быстрой выборки
    def sample(mean_goals: float) -> int:
        # Вариант: инверсия CDF через Knuth алгоритм.
        L = 2.71828 ** (-mean_goals)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p <= L:
                break
            if k > max_goals + 5:
                break
        return k - 1

    home_wins = draws = away_wins = 0
    btts = over25 = over15 = under25 = 0
    total_goals = 0
    home_goals_sum = 0
    away_goals_sum = 0
    scores: dict[str, int] = {}

    for _ in range(n_runs):
        h = min(sample(home_xg), max_goals)
        a = min(sample(away_xg), max_goals)
        t = h + a
        if h > a:
            home_wins += 1
        elif a > h:
            away_wins += 1
        else:
            draws += 1
        if h > 0 and a > 0:
            btts += 1
        if t > 2.5:
            over25 += 1
        else:
            under25 += 1
        if t > 1.5:
            over15 += 1
        total_goals += t
        home_goals_sum += h
        away_goals_sum += a
        key = f"{h}:{a}"
        scores[key] = scores.get(key, 0) + 1

    # Топ-10 распределение счётов
    top_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:10]
    score_distribution = {k: v / n_runs * 100.0 for k, v in top_scores}

    return SimulationResult(
        n_runs=n_runs,
        home_win_pct=home_wins / n_runs * 100.0,
        draw_pct=draws / n_runs * 100.0,
        away_win_pct=away_wins / n_runs * 100.0,
        btts_pct=btts / n_runs * 100.0,
        over_2_5_pct=over25 / n_runs * 100.0,
        over_1_5_pct=over15 / n_runs * 100.0,
        under_2_5_pct=under25 / n_runs * 100.0,
        avg_total_goals=total_goals / n_runs,
        avg_home_goals=home_goals_sum / n_runs,
        avg_away_goals=away_goals_sum / n_runs,
        score_distribution=score_distribution,
    )


def compare_with_analytical(
    home_xg: float, away_xg: float, *, n_runs: int = 5000, seed: int | None = None
) -> dict[str, float]:
    """Сравнивает симуляционные вероятности с аналитическими из PoissonModel.

    Возвращает словарь "home|draw|away|over_2.5|..." → MC - analytical
    (MC в процентах, analytical в процентах).
    """
    sim = simulate(home_xg, away_xg, n_runs=n_runs, seed=seed)
    h, d, a = poisson_match_probs(home_xg, away_xg)
    return {
        "home": sim.home_win_pct - h * 100.0,
        "draw": sim.draw_pct - d * 100.0,
        "away": sim.away_win_pct - a * 100.0,
    }


__all__ = ["SimulationResult", "compare_with_analytical", "simulate"]
