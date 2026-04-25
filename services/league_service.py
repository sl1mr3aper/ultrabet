"""Высокоуровневые операции по лигам и сезонам."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.sstats_client import SStatsClient


@dataclass(slots=True)
class LeagueInfo:
    league_id: int
    name: str
    country: str | None
    raw: dict[str, Any]


class LeagueService:
    def __init__(self, sstats: SStatsClient) -> None:
        self._sstats = sstats

    async def list_all(self) -> list[LeagueInfo]:
        rows = await self._sstats.list_leagues()
        out: list[LeagueInfo] = []
        for r in rows or []:
            league_id = r.get("id")
            if not isinstance(league_id, int):
                continue
            country = None
            cobj = r.get("country") or {}
            if isinstance(cobj, dict):
                country = cobj.get("name")
            out.append(LeagueInfo(
                league_id=league_id,
                name=r.get("name") or "?",
                country=country,
                raw=r,
            ))
        return out

    async def search(self, query: str) -> list[LeagueInfo]:
        rows = await self.list_all()
        q = (query or "").lower().strip()
        if not q:
            return []
        return [r for r in rows if q in (r.name or "").lower()]

    async def current_season_id(self, league_id: int) -> int | str | None:
        seasons = await self._sstats.ls_seasons(leagueId=league_id, limit=1)
        if not seasons:
            return None
        season = seasons[0]
        return season.get("uid") or season.get("id")

    async def standings(self, league_id: int) -> dict[str, Any] | None:
        season_uid = await self.current_season_id(league_id)
        if season_uid is None:
            return None
        return await self._sstats.get_standings(str(season_uid))

    async def upcoming_games(
        self, league_id: int, *, limit: int = 20, time_zone: int = 0
    ) -> list[dict[str, Any]]:
        return await self._sstats.list_games(
            league_id=league_id, upcoming=True, limit=limit, time_zone=time_zone
        )

    async def profits(self, league_id: int) -> dict[str, Any] | None:
        try:
            return await self._sstats.get_profits(league_id=league_id)
        except Exception:
            return None


__all__ = ["LeagueInfo", "LeagueService"]
