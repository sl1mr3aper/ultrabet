"""Сервис карточек игроков."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.sstats_client import SStatsClient


@dataclass(slots=True)
class PlayerProfile:
    player_id: int
    name: str
    position: str | None
    nationality: str | None
    age: int | None
    team_name: str | None
    events: list[dict[str, Any]]
    raw: dict[str, Any]


class PlayerService:
    def __init__(self, sstats: SStatsClient) -> None:
        self._sstats = sstats

    async def find(self, query: str, *, limit: int = 15) -> list[dict[str, Any]]:
        return await self._sstats.find_players(query, limit=limit)

    async def profile(self, player_id: int, *, with_events: bool = True) -> PlayerProfile | None:
        player = await self._sstats.get_player(player_id)
        if not player:
            return None
        events = []
        if with_events:
            try:
                events = await self._sstats.get_player_events(player_id)
                events = events[:15]
            except Exception:
                events = []
        team_name = None
        team_obj = player.get("team") if isinstance(player, dict) else None
        if isinstance(team_obj, dict):
            team_name = team_obj.get("name")
        nationality = None
        nat_obj = player.get("nationality") if isinstance(player, dict) else None
        if isinstance(nat_obj, dict):
            nationality = nat_obj.get("name")
        return PlayerProfile(
            player_id=player_id,
            name=(player.get("name") if isinstance(player, dict) else "?") or "?",
            position=player.get("position") if isinstance(player, dict) else None,
            nationality=nationality,
            age=player.get("age") if isinstance(player, dict) else None,
            team_name=team_name,
            events=events,
            raw=player,
        )


__all__ = ["PlayerProfile", "PlayerService"]
