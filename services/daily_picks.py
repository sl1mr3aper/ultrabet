"""Daily picks — пробег по матчам дня и сбор лучших EV предсказаний."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC

from api.sstats_client import SStatsClient
from core.value_calculator import ValueBet, ValueCalculator
from services.odds_parser import OddsParser
from services.prediction_service import PredictionResult, PredictionService


@dataclass(slots=True)
class DailyPick:
    result: PredictionResult
    bet: ValueBet


class DailyPicksGenerator:
    """Сканирует матчи на конкретную дату и собирает топ EV-ставок."""

    def __init__(
        self,
        sstats: SStatsClient,
        *,
        value_calculator: ValueCalculator | None = None,
        odds_parser: OddsParser | None = None,
        max_concurrent: int = 10,
    ) -> None:
        self._sstats = sstats
        self._value = value_calculator or ValueCalculator()
        self._odds = odds_parser or OddsParser()
        self._max_concurrent = max_concurrent

    async def for_date(
        self, date_iso: str, *, top_n: int = 10, time_zone: int = 0
    ) -> list[DailyPick]:
        games = await self._sstats.list_games(
            date=date_iso, limit=80, time_zone=time_zone
        )
        return await self._collect(games, top_n=top_n)

    async def for_today(self, time_zone: int = 0, *, top_n: int = 10) -> list[DailyPick]:
        from datetime import datetime, timedelta

        now = datetime.now(tz=UTC) + timedelta(hours=time_zone)
        return await self.for_date(now.strftime("%Y-%m-%d"), top_n=top_n, time_zone=time_zone)

    async def _collect(
        self, games: list[dict], *, top_n: int = 10
    ) -> list[DailyPick]:
        if not games:
            return []
        sem = asyncio.Semaphore(self._max_concurrent)
        service = PredictionService(
            self._sstats, value_calculator=self._value, odds_parser=self._odds
        )

        async def _process(game: dict) -> list[DailyPick]:
            game_id = game.get("id") or game.get("gameId")
            if not isinstance(game_id, int):
                return []
            async with sem:
                try:
                    res = await service.predict(game_id)
                except Exception:
                    return []
            if not res or not res.value_bets:
                return []
            return [DailyPick(result=res, bet=bet) for bet in res.value_bets[:3]]

        nested = await asyncio.gather(*(_process(g) for g in games))
        flat: list[DailyPick] = [p for sub in nested for p in sub]
        flat.sort(key=lambda p: p.bet.value_percent, reverse=True)
        return flat[:top_n]


__all__ = ["DailyPick", "DailyPicksGenerator"]
