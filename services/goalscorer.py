"""Вероятности голов для конкретных игроков.

На входе: список игроков с их минутами на поле и частотой голов. На выходе:
вероятность "забьёт в матче" и "забьёт первым".

Модель: для каждого игрока λ_игрока = голов_за_90_минут × minutes/90.
Вероятность забить хотя бы один гол = 1 - exp(-λ).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(slots=True)
class Scorer:
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    goals_per_90: float
    minutes_played: int  # ожидаемое время на поле (0-90)
    lambda_match: float = 0.0
    p_score: float = 0.0  # хотя бы один гол
    p_brace: float = 0.0  # 2+
    p_hattrick: float = 0.0  # 3+


def compute(scorer_raw: dict) -> Scorer:
    """Построить объект Scorer из словаря."""
    s = Scorer(
        player_id=int(scorer_raw.get("id") or 0),
        player_name=str(scorer_raw.get("name") or "?"),
        team_id=int(scorer_raw.get("team_id") or 0),
        team_name=str(scorer_raw.get("team_name") or "?"),
        goals_per_90=float(scorer_raw.get("goals_per_90") or 0),
        minutes_played=int(scorer_raw.get("minutes_played") or 90),
    )
    lam = s.goals_per_90 * max(0, min(s.minutes_played, 90)) / 90.0
    s.lambda_match = lam
    s.p_score = 1.0 - exp(-lam)
    s.p_brace = max(0.0, 1.0 - (1 + lam) * exp(-lam))
    s.p_hattrick = max(
        0.0, 1.0 - (1 + lam + (lam * lam) / 2.0) * exp(-lam)
    )
    return s


def rank_top_scorers(players: list[dict], *, limit: int = 10) -> list[Scorer]:
    scorers = [compute(p) for p in players]
    scorers.sort(key=lambda s: s.p_score, reverse=True)
    return scorers[:limit]


def best_pick(scorers: list[Scorer], odds_map: dict[str, float]) -> tuple[Scorer, float, float] | None:
    """Ищет игрока с лучшим value: p_score * odds - 1."""
    best: tuple[Scorer, float, float] | None = None
    for s in scorers:
        odds = odds_map.get(str(s.player_id)) or odds_map.get(s.player_name)
        if odds is None or odds <= 1.0:
            continue
        value_pct = (s.p_score * odds - 1.0) * 100.0
        if best is None or value_pct > best[2]:
            best = (s, odds, value_pct)
    return best


__all__ = ["Scorer", "best_pick", "compute", "rank_top_scorers"]
