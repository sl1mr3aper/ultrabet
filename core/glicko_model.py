"""Glicko-2: расчёт исходов из рейтингов команд.

Используется упрощённая модель Glicko-2: вероятность победы хозяев =
σ(g(RD) · (R_home + home_advantage − R_away) / 400).
"""

from __future__ import annotations

import math

HOME_ADVANTAGE_DEFAULT = 60.0  # ~ +60 ELO для дома
DRAW_BASE = 0.27  # базовый вес ничьей в футболе


def _q() -> float:
    return math.log(10) / 400.0


def _g(rd: float) -> float:
    q = _q()
    return 1.0 / math.sqrt(1.0 + 3.0 * q**2 * rd**2 / math.pi**2)


def _expected_score(r_a: float, r_b: float, rd_b: float) -> float:
    g = _g(rd_b)
    return 1.0 / (1.0 + 10 ** (-g * (r_a - r_b) / 400.0))


def glicko_outcome_probs(
    home_rating: float,
    away_rating: float,
    home_rd: float = 60.0,
    away_rd: float = 60.0,
    home_advantage: float = HOME_ADVANTAGE_DEFAULT,
) -> tuple[float, float, float]:
    """Вернуть (P(home win), P(draw), P(away win))."""
    rd_avg = (home_rd + away_rd) / 2.0
    e_home = _expected_score(home_rating + home_advantage, away_rating, rd_avg)
    e_away = 1.0 - e_home

    closeness = 1.0 - 2.0 * abs(e_home - 0.5)  # [0..1]
    p_draw = max(0.06, min(0.40, DRAW_BASE * (0.6 + 0.8 * closeness)))

    p_home = e_home * (1.0 - p_draw)
    p_away = e_away * (1.0 - p_draw)
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


def expected_goals_from_glicko(
    home_rating: float,
    away_rating: float,
    league_avg_total: float = 2.7,
    home_advantage_goals: float = 0.25,
) -> tuple[float, float]:
    """Грубая оценка xG из рейтингов: лучше команда → больше забивает."""
    diff = (home_rating + 50.0) - away_rating
    factor = math.tanh(diff / 200.0)
    base_home = league_avg_total / 2.0 + home_advantage_goals
    base_away = league_avg_total / 2.0 - home_advantage_goals
    home_xg = max(0.2, base_home * (1.0 + 0.35 * factor))
    away_xg = max(0.2, base_away * (1.0 - 0.35 * factor))
    return home_xg, away_xg


__all__ = ["expected_goals_from_glicko", "glicko_outcome_probs"]
