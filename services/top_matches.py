"""Топ матчей дня по значимости (рейтинг команд + престиж лиги)."""

from __future__ import annotations

from dataclasses import dataclass

from api.sstats_client import SStatsClient

# Простая база престижа лиг (1.0 — обычная, 1.5 — топ-5, 2.0 — главные турниры)
LEAGUE_PRESTIGE: dict[str, float] = {
    "Premier League": 2.0,
    "La Liga": 2.0,
    "Serie A": 1.9,
    "Bundesliga": 1.9,
    "Ligue 1": 1.7,
    "UEFA Champions League": 2.5,
    "UEFA Europa League": 1.8,
    "UEFA Conference League": 1.5,
    "Copa Libertadores": 1.6,
    "FA Cup": 1.4,
    "EFL Cup": 1.2,
    "Eredivisie": 1.4,
    "Primeira Liga": 1.4,
    "MLS": 1.3,
    "RPL": 1.3,
}


@dataclass(slots=True)
class RankedMatch:
    game_id: int
    home_name: str
    away_name: str
    league_name: str
    country: str | None
    date_iso: str | None
    score: float


class TopMatchesService:
    def __init__(self, sstats: SStatsClient) -> None:
        self._sstats = sstats

    async def top_for_day(
        self, date_iso: str, *, time_zone: int = 0, limit: int = 10
    ) -> list[RankedMatch]:
        games = await self._sstats.list_games(
            date=date_iso, limit=120, time_zone=time_zone
        )
        ranked: list[RankedMatch] = []
        for g in games:
            r = self._score(g)
            if r:
                ranked.append(r)
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked[:limit]

    @staticmethod
    def _score(game: dict) -> RankedMatch | None:
        gid = game.get("id") or game.get("gameId")
        if not isinstance(gid, int):
            return None
        home = (game.get("homeTeam") or {}).get("name") or "?"
        away = (game.get("awayTeam") or {}).get("name") or "?"
        league = ((game.get("season") or {}).get("league") or {}).get("name") or "?"
        country = None
        season = game.get("season") or {}
        if isinstance(season, dict):
            league_obj = season.get("league") or {}
            if isinstance(league_obj, dict):
                c = league_obj.get("country") or {}
                if isinstance(c, dict):
                    country = c.get("name")
        prestige = LEAGUE_PRESTIGE.get(league or "", 1.0)
        rating_home = ((game.get("homeTeam") or {}).get("rating") or 1500.0)
        rating_away = ((game.get("awayTeam") or {}).get("rating") or 1500.0)
        try:
            avg_rating = (float(rating_home) + float(rating_away)) / 2.0
        except (TypeError, ValueError):
            avg_rating = 1500.0
        # значимость = престиж × средний рейтинг / 1500
        score = prestige * (avg_rating / 1500.0)
        return RankedMatch(
            game_id=gid,
            home_name=home,
            away_name=away,
            league_name=league,
            country=country,
            date_iso=game.get("date") or game.get("gameDate"),
            score=score,
        )


__all__ = ["LEAGUE_PRESTIGE", "RankedMatch", "TopMatchesService"]
