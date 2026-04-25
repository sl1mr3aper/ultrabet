"""Анализ очных встреч (H2H, head-to-head)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from api.sstats_client import SStatsClient
from services.match_finder import _parse_date


@dataclass(slots=True)
class H2HMatch:
    game_id: int
    date_iso: str | None
    home_name: str
    away_name: str
    home_score: int | None
    away_score: int | None
    league_name: str | None

    @property
    def winner(self) -> str | None:
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return "home"
        if self.home_score < self.away_score:
            return "away"
        return "draw"


@dataclass(slots=True)
class H2HSummary:
    matches: list[H2HMatch] = field(default_factory=list)
    home_wins: int = 0
    away_wins: int = 0
    draws: int = 0
    avg_total_goals: float = 0.0
    btts_count: int = 0

    @property
    def total_played(self) -> int:
        return self.home_wins + self.away_wins + self.draws

    @property
    def home_win_pct(self) -> float:
        n = self.total_played
        return (self.home_wins / n * 100.0) if n else 0.0

    @property
    def away_win_pct(self) -> float:
        n = self.total_played
        return (self.away_wins / n * 100.0) if n else 0.0

    @property
    def draw_pct(self) -> float:
        n = self.total_played
        return (self.draws / n * 100.0) if n else 0.0

    @property
    def btts_pct(self) -> float:
        n = self.total_played
        return (self.btts_count / n * 100.0) if n else 0.0


class H2HService:
    """Загружает прошлые встречи и считает агрегаты."""

    def __init__(self, sstats: SStatsClient, *, max_matches: int = 10) -> None:
        self._sstats = sstats
        self._max_matches = max_matches

    async def fetch(self, home_team_id: int, away_team_id: int) -> H2HSummary:
        rows = await self._sstats.query_games(
            {"team1Id": home_team_id, "team2Id": away_team_id, "limit": self._max_matches}
        )
        matches = [self._row_to_match(r) for r in rows or []]
        matches = [m for m in matches if m is not None]
        matches.sort(key=lambda m: _parse_date(m.date_iso) or datetime.min, reverse=True)
        summary = H2HSummary(matches=matches[: self._max_matches])
        for m in summary.matches:
            if m.winner == "home":
                if m.home_name and m.home_name == matches[0].home_name:
                    summary.home_wins += 1
                else:
                    summary.away_wins += 1
            elif m.winner == "away":
                if m.home_name and m.home_name == matches[0].home_name:
                    summary.away_wins += 1
                else:
                    summary.home_wins += 1
            elif m.winner == "draw":
                summary.draws += 1
            if m.home_score and m.away_score:
                summary.avg_total_goals += m.home_score + m.away_score
                if m.home_score > 0 and m.away_score > 0:
                    summary.btts_count += 1
        if summary.total_played:
            summary.avg_total_goals = summary.avg_total_goals / summary.total_played
        return summary

    @staticmethod
    def _row_to_match(raw: dict[str, Any]) -> H2HMatch | None:
        if not isinstance(raw, dict):
            return None
        game_id = raw.get("id") or raw.get("gameId")
        if not isinstance(game_id, int):
            return None
        home_team = raw.get("homeTeam") or {}
        away_team = raw.get("awayTeam") or {}
        score = raw.get("score") or raw.get("result") or {}
        home_score = score.get("home") if isinstance(score, dict) else None
        away_score = score.get("away") if isinstance(score, dict) else None
        league_name = None
        season = raw.get("season") or {}
        if isinstance(season, dict):
            league_obj = season.get("league") or {}
            if isinstance(league_obj, dict):
                league_name = league_obj.get("name")
        return H2HMatch(
            game_id=game_id,
            date_iso=raw.get("date") or raw.get("gameDate"),
            home_name=home_team.get("name") if isinstance(home_team, dict) else "?",
            away_name=away_team.get("name") if isinstance(away_team, dict) else "?",
            home_score=home_score if isinstance(home_score, int) else None,
            away_score=away_score if isinstance(away_score, int) else None,
            league_name=league_name,
        )


__all__ = ["H2HMatch", "H2HService", "H2HSummary"]
