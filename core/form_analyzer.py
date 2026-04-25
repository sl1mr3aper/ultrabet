"""Анализ формы команды по последним матчам.

Принимает список последних матчей с точки зрения конкретной команды и считает
рейтинг формы (0..1), серию (W/D/L), среднее количество забитых/пропущенных,
взвешенный xG-баланс.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FormSnapshot:
    games_count: int
    wins: int
    draws: int
    losses: int
    goals_for: float
    goals_against: float
    xg_for: float
    xg_against: float
    streak_repr: str  # "WWDLW"
    weighted_score: float  # 0..1, последние матчи весят больше

    @property
    def points(self) -> int:
        return self.wins * 3 + self.draws

    @property
    def avg_goals_for(self) -> float:
        return self.goals_for / self.games_count if self.games_count else 0.0

    @property
    def avg_goals_against(self) -> float:
        return self.goals_against / self.games_count if self.games_count else 0.0


def _outcome_for_team(game: dict[str, Any], team_id: int) -> str | None:
    home_team = (game.get("homeTeam") or {})
    away_team = (game.get("awayTeam") or {})
    score = game.get("score") or game.get("result") or {}
    if not isinstance(score, dict):
        return None
    home = score.get("home")
    away = score.get("away")
    if home is None or away is None:
        return None
    if home_team.get("id") == team_id:
        if home > away:
            return "W"
        if home < away:
            return "L"
        return "D"
    if away_team.get("id") == team_id:
        if away > home:
            return "W"
        if away < home:
            return "L"
        return "D"
    return None


def analyze_form(team_id: int, games: list[dict[str, Any]]) -> FormSnapshot:
    """Анализирует форму, веса по убыванию давности.

    `games` ожидается отсортирован от самого последнего к более старым.
    """
    wins = draws = losses = 0
    gf = ga = 0.0
    xgf = xga = 0.0
    streak: list[str] = []
    weighted_score = 0.0
    weight_sum = 0.0
    for i, g in enumerate(games):
        outcome = _outcome_for_team(g, team_id)
        if outcome is None:
            continue
        weight = 1.0 / (i + 1)  # 1, 0.5, 0.33, …
        weight_sum += weight
        if outcome == "W":
            wins += 1
            weighted_score += weight * 1.0
        elif outcome == "D":
            draws += 1
            weighted_score += weight * 0.5
        else:
            losses += 1
        streak.append(outcome)
        score = g.get("score") or g.get("result") or {}
        if isinstance(score, dict):
            home = score.get("home")
            away = score.get("away")
            home_id = (g.get("homeTeam") or {}).get("id")
            if home is not None and away is not None:
                if home_id == team_id:
                    gf += float(home)
                    ga += float(away)
                else:
                    gf += float(away)
                    ga += float(home)
        xg = g.get("xg") or {}
        if isinstance(xg, dict):
            xg_home = xg.get("home")
            xg_away = xg.get("away")
            home_id = (g.get("homeTeam") or {}).get("id")
            if xg_home is not None and xg_away is not None:
                if home_id == team_id:
                    xgf += float(xg_home)
                    xga += float(xg_away)
                else:
                    xgf += float(xg_away)
                    xga += float(xg_home)

    n = wins + draws + losses
    return FormSnapshot(
        games_count=n,
        wins=wins,
        draws=draws,
        losses=losses,
        goals_for=gf,
        goals_against=ga,
        xg_for=xgf,
        xg_against=xga,
        streak_repr="".join(streak),
        weighted_score=weighted_score / weight_sum if weight_sum else 0.0,
    )


__all__ = ["FormSnapshot", "analyze_form"]
