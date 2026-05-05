"""Glicko-2: расчёт исходов из рейтингов команд.

Используется упрощённая модель Glicko-2: вероятность победы хозяев =
σ(g(RD) · (R_home + home_advantage − R_away) / 400).

Per-league HOME_ADVANTAGE: разные лиги имеют различное домашнее
преимущество. Стандартные значения из литературы / калибровки:
  - АПЛ, Бундеслига: ~200-250 ELO
  - Скандинавские лиги: ~350-400 ELO
  - Латинская Америка: ~400-600 ELO
  - Дефолт: 60 ELO (для неизвестных лиг)
"""

from __future__ import annotations

import math

HOME_ADVANTAGE_DEFAULT = 60.0
DRAW_BASE = 0.27

# Per-league home advantage (ключ = league_id).
# Будет обновляться из CalibrationService / SelfLearner.
_LEAGUE_HOME_ADVANTAGE: dict[int, float] = {}

# Региональные дефолты (когда нет данных по конкретной лиге).
_REGION_HOME_ADVANTAGE: dict[str, float] = {
    "england": 55.0,
    "germany": 55.0,
    "spain": 60.0,
    "italy": 65.0,
    "france": 55.0,
    "portugal": 60.0,
    "netherlands": 50.0,
    "belgium": 50.0,
    "turkey": 75.0,
    "greece": 70.0,
    "russia": 65.0,
    "ukraine": 60.0,
    "brazil": 80.0,
    "argentina": 85.0,
    "mexico": 75.0,
    "colombia": 80.0,
    "chile": 70.0,
    "peru": 75.0,
    "ecuador": 90.0,
    "bolivia": 100.0,  # высокогорье
    "usa": 55.0,
    "japan": 55.0,
    "south korea": 55.0,
    "china": 60.0,
    "australia": 55.0,
    "sweden": 60.0,
    "norway": 65.0,
    "denmark": 55.0,
    "finland": 60.0,
    "iceland": 70.0,
    "scotland": 60.0,
    "ireland": 55.0,
    "poland": 65.0,
    "czech republic": 60.0,
    "croatia": 60.0,
    "serbia": 65.0,
    "romania": 65.0,
    "egypt": 70.0,
    "south africa": 65.0,
    "morocco": 70.0,
    "tunisia": 65.0,
    "saudi arabia": 70.0,
    "iran": 75.0,
    "india": 65.0,
    "indonesia": 70.0,
}


def set_league_home_advantage(league_id: int, ha: float) -> None:
    """Установить домашнее преимущество для конкретной лиги."""
    _LEAGUE_HOME_ADVANTAGE[league_id] = ha


def get_home_advantage(
    league_id: int | None = None,
    country: str | None = None,
) -> float:
    """Получить home advantage: сначала лига, потом регион, потом дефолт."""
    if league_id is not None and league_id in _LEAGUE_HOME_ADVANTAGE:
        return _LEAGUE_HOME_ADVANTAGE[league_id]
    if country:
        c = country.lower().strip()
        if c in _REGION_HOME_ADVANTAGE:
            return _REGION_HOME_ADVANTAGE[c]
    return HOME_ADVANTAGE_DEFAULT


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
    *,
    league_id: int | None = None,
    country: str | None = None,
) -> tuple[float, float, float]:
    """Вернуть (P(home win), P(draw), P(away win)).

    Если league_id или country переданы, home_advantage берётся из
    per-league таблицы (если не передано явно другое значение).
    """
    if home_advantage == HOME_ADVANTAGE_DEFAULT and (league_id or country):
        home_advantage = get_home_advantage(league_id, country)

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


__all__ = [
    "expected_goals_from_glicko",
    "get_home_advantage",
    "glicko_outcome_probs",
    "set_league_home_advantage",
]
