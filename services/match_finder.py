"""Поиск матчей по названиям команд."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.sstats_client import SStatsClient


@dataclass(slots=True)
class MatchCandidate:
    game_id: int
    home_id: int
    home_name: str
    away_id: int
    away_name: str
    league_name: str
    league_country: str | None
    date_iso: str
    status: int | None
    raw: dict[str, Any]


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(value.split(".")[0].replace("Z", ""), fmt.replace("Z", ""))
                    return dt.replace(tzinfo=UTC)
                except ValueError:
                    continue
    return None


def _candidate_from_raw(raw: dict[str, Any]) -> MatchCandidate | None:
    home = raw.get("homeTeam") or {}
    away = raw.get("awayTeam") or {}
    season = raw.get("season") or {}
    league = season.get("league") if isinstance(season, dict) else {}
    league_name = (league or {}).get("name") if isinstance(league, dict) else None
    country = None
    if isinstance(league, dict):
        c = league.get("country")
        if isinstance(c, dict):
            country = c.get("name")
    try:
        return MatchCandidate(
            game_id=int(raw.get("id")),
            home_id=int(home.get("id")) if home.get("id") is not None else 0,
            home_name=str(home.get("name") or "?"),
            away_id=int(away.get("id")) if away.get("id") is not None else 0,
            away_name=str(away.get("name") or "?"),
            league_name=str(league_name or "—"),
            league_country=country,
            date_iso=str(raw.get("date") or ""),
            status=raw.get("status") if isinstance(raw.get("status"), int) else None,
            raw=raw,
        )
    except (TypeError, ValueError) as exc:
        logger.debug("can't build candidate: {}", exc)
        return None


class MatchFinder:
    """Поиск матча двух команд по их именам и идентификаторам."""

    def __init__(self, client: SStatsClient) -> None:
        self._client = client

    async def search_teams(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return await self._client.search_teams(query, limit=limit)

    async def find_match_for_teams(
        self,
        home_team_id: int,
        away_team_id: int,
    ) -> MatchCandidate | None:
        """Найти ближайший к 'сейчас' матч между двумя командами."""
        try:
            upcoming = await self._client.list_games(
                both_teams=[home_team_id, away_team_id],
                upcoming=True,
                limit=10,
                order=1,
            )
        except Exception as exc:
            logger.debug("upcoming search failed: {}", exc)
            upcoming = []
        for raw in upcoming:
            cand = _candidate_from_raw(raw)
            if cand is not None and cand.home_id == home_team_id and cand.away_id == away_team_id:
                return cand

        try:
            live = await self._client.list_games(
                both_teams=[home_team_id, away_team_id],
                live=True,
                limit=10,
            )
        except Exception:
            live = []
        for raw in live:
            cand = _candidate_from_raw(raw)
            if cand is not None and cand.home_id == home_team_id and cand.away_id == away_team_id:
                return cand

        try:
            anything = await self._client.list_games(
                both_teams=[home_team_id, away_team_id],
                limit=20,
                order=-1,
            )
        except Exception:
            anything = []
        candidates: list[MatchCandidate] = []
        for raw in anything:
            cand = _candidate_from_raw(raw)
            if cand is None:
                continue
            if cand.home_id != home_team_id or cand.away_id != away_team_id:
                continue
            candidates.append(cand)
        if candidates:
            now = datetime.now(tz=UTC)
            candidates.sort(
                key=lambda c: abs(((_parse_date(c.date_iso) or now) - now).total_seconds())
            )
            return candidates[0]
        return None


__all__ = ["MatchCandidate", "MatchFinder", "_candidate_from_raw", "_parse_date"]
