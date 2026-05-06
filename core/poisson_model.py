"""Двойная Пуассон-модель футбольного матча с Dixon-Coles коррекцией.

Dixon-Coles (1997) корректирует вероятности низких счётов (0:0, 1:0, 0:1, 1:1),
которые стандартная Пуассон-модель систематически недооценивает.

Параметр rho ∈ [-1, 0] контролирует силу коррекции:
  rho=0 → чистый Пуассон (без коррекции)
  rho=-0.13 → типичное значение для топ-лиг
"""

from __future__ import annotations

import math

MAX_GOALS = 10

# Dixon-Coles: типичное rho для большинства лиг.
# Оптимизируется по данным, но -0.13 — хороший дефолт из литературы.
DC_RHO_DEFAULT = -0.13


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def _dixon_coles_tau(
    i: int, j: int, lam_home: float, lam_away: float, rho: float,
) -> float:
    """Dixon-Coles коррекционный множитель tau для P(home=i, away=j).

    Корректирует только ячейки (0,0), (1,0), (0,1), (1,1).
    Для остальных счётов tau = 1.0 (без коррекции).
    """
    if rho == 0.0:
        return 1.0
    if i == 0 and j == 0:
        return 1.0 - lam_home * lam_away * rho
    if i == 1 and j == 0:
        return 1.0 + lam_away * rho
    if i == 0 and j == 1:
        return 1.0 + lam_home * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def correct_score_distribution(
    home_xg: float,
    away_xg: float,
    max_goals: int = MAX_GOALS,
    *,
    rho: float = DC_RHO_DEFAULT,
) -> list[list[float]]:
    """Матрица P(home_score=i, away_score=j) с Dixon-Coles коррекцией."""
    home_xg = max(home_xg, 0.05)
    away_xg = max(away_xg, 0.05)
    home_pmf = [_poisson_pmf(i, home_xg) for i in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(j, away_xg) for j in range(max_goals + 1)]
    matrix = [
        [
            home_pmf[i] * away_pmf[j]
            * _dixon_coles_tau(i, j, home_xg, away_xg, rho)
            for j in range(max_goals + 1)
        ]
        for i in range(max_goals + 1)
    ]
    total = sum(sum(row) for row in matrix)
    if total <= 0:
        return matrix
    return [[v / total for v in row] for row in matrix]


def poisson_match_probs(
    home_xg: float, away_xg: float, *, rho: float = DC_RHO_DEFAULT,
) -> tuple[float, float, float]:
    matrix = correct_score_distribution(home_xg, away_xg, rho=rho)
    n = len(matrix)
    p_home = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
    p_draw = sum(matrix[i][i] for i in range(n))
    p_away = sum(matrix[i][j] for i in range(n) for j in range(n) if i < j)
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return p_home / total, p_draw / total, p_away / total


def over_under_probabilities(
    home_xg: float,
    away_xg: float,
    thresholds: tuple[float, ...] = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5),
    *,
    rho: float = DC_RHO_DEFAULT,
) -> dict[float, tuple[float, float]]:
    matrix = correct_score_distribution(home_xg, away_xg, rho=rho)
    n = len(matrix)
    result: dict[float, tuple[float, float]] = {}
    for t in thresholds:
        over = 0.0
        under = 0.0
        for i in range(n):
            for j in range(n):
                total_goals = i + j
                if total_goals > t:
                    over += matrix[i][j]
                else:
                    under += matrix[i][j]
        s = over + under
        if s > 0:
            result[t] = (over / s, under / s)
    return result


def team_total_probabilities(
    home_xg: float,
    away_xg: float,
    home_thresholds: tuple[float, ...] = (0.5, 1.5, 2.5),
    away_thresholds: tuple[float, ...] = (0.5, 1.5, 2.5),
) -> dict[str, dict[float, tuple[float, float]]]:
    home_xg = max(home_xg, 0.05)
    away_xg = max(away_xg, 0.05)
    out: dict[str, dict[float, tuple[float, float]]] = {"home": {}, "away": {}}
    for side, lam, thresholds in (
        ("home", home_xg, home_thresholds),
        ("away", away_xg, away_thresholds),
    ):
        for t in thresholds:
            over = sum(_poisson_pmf(k, lam) for k in range(MAX_GOALS + 1) if k > t)
            under = sum(_poisson_pmf(k, lam) for k in range(MAX_GOALS + 1) if k <= t)
            s = over + under
            if s > 0:
                out[side][t] = (over / s, under / s)
    return out


def btts_probabilities(
    home_xg: float, away_xg: float, *, rho: float = DC_RHO_DEFAULT,
) -> tuple[float, float]:
    """BTTS с Dixon-Coles коррекцией через полную матрицу."""
    matrix = correct_score_distribution(home_xg, away_xg, rho=rho)
    n = len(matrix)
    p_no = 0.0
    for i in range(n):
        p_no += matrix[i][0]  # away=0
    for j in range(1, n):
        p_no += matrix[0][j]  # home=0, away>0
    p_yes = max(0.0, 1.0 - p_no)
    return p_yes, p_no


def handicap_probabilities(matrix: list[list[float]]) -> dict[str, float]:
    """Азиатские форы ±1.5 и ±2.5."""
    n = len(matrix)
    home_minus_15 = sum(matrix[i][j] for i in range(n) for j in range(n) if i - j > 1)
    home_plus_15 = sum(matrix[i][j] for i in range(n) for j in range(n) if i - j > -2)
    away_minus_15 = sum(matrix[i][j] for i in range(n) for j in range(n) if j - i > 1)
    away_plus_15 = sum(matrix[i][j] for i in range(n) for j in range(n) if j - i > -2)
    home_minus_25 = sum(matrix[i][j] for i in range(n) for j in range(n) if i - j > 2)
    home_plus_25 = sum(matrix[i][j] for i in range(n) for j in range(n) if i - j > -3)
    away_minus_25 = sum(matrix[i][j] for i in range(n) for j in range(n) if j - i > 2)
    away_plus_25 = sum(matrix[i][j] for i in range(n) for j in range(n) if j - i > -3)
    return {
        "home_+1.5": min(max(home_plus_15, 0.0), 1.0),
        "home_-1.5": min(max(home_minus_15, 0.0), 1.0),
        "away_+1.5": min(max(away_plus_15, 0.0), 1.0),
        "away_-1.5": min(max(away_minus_15, 0.0), 1.0),
        "home_+2.5": min(max(home_plus_25, 0.0), 1.0),
        "home_-2.5": min(max(home_minus_25, 0.0), 1.0),
        "away_+2.5": min(max(away_plus_25, 0.0), 1.0),
        "away_-2.5": min(max(away_minus_25, 0.0), 1.0),
    }


def top_correct_scores(
    home_xg: float,
    away_xg: float,
    top_n: int = 5,
    *,
    rho: float = DC_RHO_DEFAULT,
) -> list[tuple[int, int, float]]:
    matrix = correct_score_distribution(home_xg, away_xg, rho=rho)
    flat: list[tuple[int, int, float]] = []
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            flat.append((i, j, p))
    flat.sort(key=lambda x: x[2], reverse=True)
    return flat[:top_n]


# ── Time-decay ────────────────────────────────────────────────────
def time_decay_weight(days_ago: float, tau: float = 547.5) -> float:
    """Экспоненциальный time-decay вес. tau=547.5 дней (~18 месяцев)."""
    if days_ago <= 0:
        return 1.0
    return math.exp(-days_ago / tau)


# ── Shrinkage ─────────────────────────────────────────────────────
def shrink_xg(
    team_xg: float,
    league_avg: float,
    games_played: int,
    *,
    shrinkage_games: int = 10,
) -> float:
    """Регрессия к среднему: при малой выборке доверяем среднему лиги.

    weight = games / (games + shrinkage_games)
    xG = weight * team_xG + (1 - weight) * league_avg
    """
    if games_played <= 0:
        return league_avg
    w = games_played / (games_played + shrinkage_games)
    return w * team_xg + (1.0 - w) * league_avg


__all__ = [
    "DC_RHO_DEFAULT",
    "btts_probabilities",
    "correct_score_distribution",
    "handicap_probabilities",
    "over_under_probabilities",
    "poisson_match_probs",
    "shrink_xg",
    "team_total_probabilities",
    "time_decay_weight",
    "top_correct_scores",
]
