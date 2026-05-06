"""P0-10: прогрев кэша SStats для матчей ближайших 24 ч.

Запускается раз в 10 минут фоновой задачей. Идея — пока пользователь
не нажал на матч, уже подтянуть `Games/{id}`, `get_glicko`,
`get_full_match_data` в внутренний TTL-кэш клиента SStats. В результате
на клик от пользователя бот отдаёт ответ почти мгновенно, без сетевых
round-trip'ов.

Никаких внешних зависимостей (Redis ещё не подключён) — `SStatsClient`
сам использует `TTLCache` внутри.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from api.sstats_client import SStatsClient


class CacheWarmer:
    def __init__(
        self,
        client: SStatsClient,
        *,
        leagues_per_run: int = 30,
        per_league: int = 10,
        horizon_hours: int = 24,
    ) -> None:
        self._client = client
        self._leagues_per_run = leagues_per_run
        self._per_league = per_league
        self._horizon_hours = horizon_hours

    async def warm_once(self) -> int:
        """Один проход. Возвращает количество прогретых матчей."""
        horizon = datetime.now(tz=UTC) + timedelta(hours=self._horizon_hours)
        now = datetime.now(tz=UTC)
        try:
            leagues = await self._client.list_leagues()
        except Exception as exc:
            logger.debug("CacheWarmer: list_leagues failed: {}", exc)
            return 0
        leagues = [
            lg for lg in (leagues or []) if isinstance(lg, dict)
        ][: self._leagues_per_run]
        warmed = 0
        for lg in leagues:
            lg_id = lg.get("id")
            if not lg_id:
                continue
            try:
                games = await self._client.list_games(
                    league_id=int(lg_id),
                    order=1,
                    limit=self._per_league,
                )
            except Exception as exc:
                logger.debug("CacheWarmer: list_games({}): {}", lg_id, exc)
                continue
            for g in games or []:
                if not isinstance(g, dict):
                    continue
                game_id = g.get("id")
                if not game_id:
                    continue
                game_dt = _parse_dt(g)
                if game_dt is None:
                    continue
                if game_dt < now or game_dt > horizon:
                    continue
                if await self._warm_game(int(game_id)):
                    warmed += 1
        logger.debug("CacheWarmer: прогрето {} матчей", warmed)
        return warmed

    async def _warm_game(self, game_id: int) -> bool:
        """Грузим в кэш клиента минимально-необходимый набор данных."""
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(_silent(self._client.get_game(game_id)))
                tg.create_task(_silent(self._client.get_glicko(game_id)))
                tg.create_task(_silent(self._client.get_live_odds(game_id)))
        except Exception:
            return False
        return True


async def _silent(coro: Any) -> None:
    try:
        await coro
    except Exception:
        pass


def _parse_dt(g: dict[str, Any]) -> datetime | None:
    raw = g.get("date") or g.get("startDate") or g.get("dateUTC")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


__all__ = ["CacheWarmer"]
