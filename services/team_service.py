"""Сервис карточек команд."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.sstats_client import SStatsClient


@dataclass(slots=True)
class TeamProfile:
    team_id: int
    name: str
    country: str | None
    league: str | None
    glicko_rating: float | None
    last_games: list[dict[str, Any]]
    upcoming: list[dict[str, Any]]
    raw: dict[str, Any]


class TeamService:
    def __init__(self, sstats: SStatsClient) -> None:
        self._sstats = sstats

    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return await self._sstats.search_teams(query, limit=limit)

    async def profile(self, team_id: int) -> TeamProfile | None:
        team = await self._sstats.get_team(team_id)
        if not team:
            return None
        rating = None
        country = None
        league = None
        if isinstance(team, dict):
            rating = (team.get("glicko") or {}).get("rating")
            country_obj = team.get("country") or {}
            if isinstance(country_obj, dict):
                country = country_obj.get("name")
            league_obj = team.get("league") or {}
            if isinstance(league_obj, dict):
                league = league_obj.get("name")
        last = await self._sstats.list_games(team=team_id, ended=True, limit=10)
        upcoming = await self._sstats.list_games(team=team_id, upcoming=True, limit=5)
        return TeamProfile(
            team_id=team_id,
            name=(team.get("name") if isinstance(team, dict) else "?") or "?",
            country=country,
            league=league,
            glicko_rating=float(rating) if rating is not None else None,
            last_games=last or [],
            upcoming=upcoming or [],
            raw=team,
        )


__all__ = ["TeamProfile", "TeamService"]
