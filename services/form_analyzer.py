"""Анализ формы команд по последним N матчам.

Отдельно от accuracy_boost: этот модуль считает более подробные метрики формы
(очки за 5/10/15 игр, голы забитые/пропущенные, xG против, clean sheets, BTTS rate)
и отдаёт текстовый отчёт для /form команды.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FormStat:
    team_id: int
    team_name: str
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    clean_sheets: int = 0
    failed_to_score: int = 0
    btts_games: int = 0
    streak: str = ""  # последние 5 символов WDL
    points_per_game: float = 0.0
    goals_for_per_game: float = 0.0
    goals_against_per_game: float = 0.0
    win_rate_pct: float = 0.0
    draw_rate_pct: float = 0.0
    loss_rate_pct: float = 0.0
    clean_sheet_rate_pct: float = 0.0
    btts_rate_pct: float = 0.0
    recent_results: list[str] = field(default_factory=list)  # ["W","D","L",...]


def _outcome_for_team(game: dict, team_id: int) -> tuple[str, int, int]:
    home_id = (game.get("home_team") or {}).get("id")
    away_id = (game.get("away_team") or {}).get("id")
    score = game.get("score") or {}
    hs = int(score.get("home") or 0)
    as_ = int(score.get("away") or 0)
    if home_id == team_id:
        if hs > as_:
            return "W", hs, as_
        if hs == as_:
            return "D", hs, as_
        return "L", hs, as_
    if away_id == team_id:
        if as_ > hs:
            return "W", as_, hs
        if as_ == hs:
            return "D", as_, hs
        return "L", as_, hs
    return "?", 0, 0


def analyze_form(
    team_id: int, team_name: str, games: list[dict], *, limit: int = 10
) -> FormStat:
    stat = FormStat(team_id=team_id, team_name=team_name)
    tail = games[:limit] if games else []
    if not tail:
        return stat
    stat.games = len(tail)
    streak_chars: list[str] = []
    for game in tail:
        outcome, goals_for, goals_against = _outcome_for_team(game, team_id)
        if outcome == "?":
            continue
        stat.goals_for += goals_for
        stat.goals_against += goals_against
        if goals_against == 0:
            stat.clean_sheets += 1
        if goals_for == 0:
            stat.failed_to_score += 1
        if goals_for > 0 and goals_against > 0:
            stat.btts_games += 1
        if outcome == "W":
            stat.wins += 1
            stat.points += 3
        elif outcome == "D":
            stat.draws += 1
            stat.points += 1
        elif outcome == "L":
            stat.losses += 1
        streak_chars.append(outcome)
        stat.recent_results.append(outcome)

    g = stat.games or 1
    stat.streak = "".join(streak_chars[-5:])
    stat.points_per_game = stat.points / g
    stat.goals_for_per_game = stat.goals_for / g
    stat.goals_against_per_game = stat.goals_against / g
    stat.win_rate_pct = stat.wins / g * 100.0
    stat.draw_rate_pct = stat.draws / g * 100.0
    stat.loss_rate_pct = stat.losses / g * 100.0
    stat.clean_sheet_rate_pct = stat.clean_sheets / g * 100.0
    stat.btts_rate_pct = stat.btts_games / g * 100.0
    return stat


def compare_form(a: FormStat, b: FormStat) -> dict[str, str]:
    """Сравнивает двух команд и возвращает оценки в виде строк."""
    return {
        "attack": (
            f"{a.team_name} забивает {a.goals_for_per_game:.2f} vs "
            f"{b.team_name} — {b.goals_for_per_game:.2f}"
        ),
        "defense": (
            f"{a.team_name} пропускает {a.goals_against_per_game:.2f} vs "
            f"{b.team_name} — {b.goals_against_per_game:.2f}"
        ),
        "points": (
            f"{a.team_name} очки/матч: {a.points_per_game:.2f} vs "
            f"{b.team_name} — {b.points_per_game:.2f}"
        ),
    }


def streak_emoji(streak: str) -> str:
    """Маппим строку WDL в эмодзи."""
    return "".join(
        {"W": "🟢", "D": "🟡", "L": "🔴"}.get(ch, "⚪") for ch in streak[-5:]
    )


__all__ = ["FormStat", "analyze_form", "compare_form", "streak_emoji"]
