"""Расчёт "силы лиги" для учёта в прогнозах.

Лиги разной силы (APL, Бундеслига, лиги Центральной Азии) дают разный
базовый xG и разный уровень рейтинга команд. Модель xG должна
корректироваться с учётом средних показателей лиги за сезон.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev


@dataclass(slots=True)
class LeagueStats:
    league_id: int
    league_name: str
    country: str
    matches_played: int
    avg_goals_home: float
    avg_goals_away: float
    avg_total_goals: float
    home_win_pct: float
    draw_pct: float
    away_win_pct: float
    btts_pct: float
    over_2_5_pct: float
    goal_stdev: float  # стандартное отклонение тотала, мерит дисперсию


def compute_league_stats(
    league_id: int,
    league_name: str,
    country: str,
    games: list[dict],
) -> LeagueStats:
    """games — список матчей с полями home_score/away_score."""
    if not games:
        return LeagueStats(
            league_id=league_id,
            league_name=league_name,
            country=country,
            matches_played=0,
            avg_goals_home=0,
            avg_goals_away=0,
            avg_total_goals=0,
            home_win_pct=0,
            draw_pct=0,
            away_win_pct=0,
            btts_pct=0,
            over_2_5_pct=0,
            goal_stdev=0,
        )

    home_goals = []
    away_goals = []
    home_wins = draws = away_wins = 0
    btts = 0
    over_25 = 0
    totals = []

    for g in games:
        h = int(g.get("home_score") or 0)
        a = int(g.get("away_score") or 0)
        home_goals.append(h)
        away_goals.append(a)
        totals.append(h + a)
        if h > a:
            home_wins += 1
        elif h < a:
            away_wins += 1
        else:
            draws += 1
        if h > 0 and a > 0:
            btts += 1
        if h + a > 2.5:
            over_25 += 1

    n = len(games)
    return LeagueStats(
        league_id=league_id,
        league_name=league_name,
        country=country,
        matches_played=n,
        avg_goals_home=mean(home_goals),
        avg_goals_away=mean(away_goals),
        avg_total_goals=mean(totals),
        home_win_pct=home_wins / n * 100.0,
        draw_pct=draws / n * 100.0,
        away_win_pct=away_wins / n * 100.0,
        btts_pct=btts / n * 100.0,
        over_2_5_pct=over_25 / n * 100.0,
        goal_stdev=pstdev(totals) if len(totals) > 1 else 0.0,
    )


def normalize_xg(xg: float, league_avg: float) -> float:
    """Приводит xG команды к "средней лиге" (где 1.35 — мировая норма)."""
    base = 1.35
    if league_avg <= 0:
        return xg
    return xg * (base / league_avg)


__all__ = ["LeagueStats", "compute_league_stats", "normalize_xg"]
