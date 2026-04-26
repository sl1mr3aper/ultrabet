"""Мониторинг live-матчей: собирает изменения коэффициентов и ищет валуйные.

Используется как periodic-задача Scheduler для отправки уведомлений
пользователям, подписанным на live-алерты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api.sstats_client import SStatsClient
from core.value_calculator import ValueBet, ValueCalculator
from loguru import logger


@dataclass(slots=True)
class LiveMatchSnapshot:
    game_id: int
    home_name: str
    away_name: str
    league_name: str
    minute: int | None
    home_score: int
    away_score: int
    odds_map: dict[str, float] = field(default_factory=dict)
    value_bets: list[ValueBet] = field(default_factory=list)


class LiveMonitor:
    """Периодически опрашивает live-матчи и ищет изменения/валуйность."""

    def __init__(
        self,
        client: SStatsClient,
        *,
        value_calculator: ValueCalculator,
        min_value_pct: float = 8.0,
    ) -> None:
        self._client = client
        self._value = value_calculator
        self._min_value_pct = min_value_pct
        self._last_snapshots: dict[int, LiveMatchSnapshot] = {}

    async def snapshot(self) -> list[LiveMatchSnapshot]:
        """Собрать все live-матчи с их текущими коэфами."""
        try:
            raw = await self._client.list_games(live=True, limit=50)
        except Exception as exc:
            logger.warning("live снапшот провален: {}", exc)
            return []
        out: list[LiveMatchSnapshot] = []
        for g in raw or []:
            if not isinstance(g, dict):
                continue
            gid = int(g.get("id") or 0)
            if gid == 0:
                continue
            home = g.get("home_team") or g.get("home") or {}
            away = g.get("away_team") or g.get("away") or {}
            lg = g.get("league") or {}
            score = g.get("score") or {}
            snap = LiveMatchSnapshot(
                game_id=gid,
                home_name=str(home.get("name", "?")),
                away_name=str(away.get("name", "?")),
                league_name=str(lg.get("name", "?")),
                minute=g.get("minute"),
                home_score=int(score.get("home", 0)),
                away_score=int(score.get("away", 0)),
            )
            try:
                live_odds = await self._client.get_live_odds(gid)
                snap.odds_map = _flatten_odds(live_odds)
            except Exception as exc:
                logger.debug("live odds для {} провалены: {}", gid, exc)
            out.append(snap)
        return out

    def detect_value(
        self,
        snap: LiveMatchSnapshot,
        probabilities: dict[str, float],
    ) -> list[ValueBet]:
        """Ищем валуйные ставки в текущем снапшоте."""
        bets: list[ValueBet] = []
        for market_key, odds in snap.odds_map.items():
            prob = probabilities.get(market_key)
            if prob is None or prob <= 0 or odds <= 1.0:
                continue
            vb = self._value.calculate(
                market_key=market_key, probability=prob, actual_odds=odds
            )
            if vb.is_value and vb.value_percent >= self._min_value_pct:
                bets.append(vb)
        bets.sort(key=lambda b: b.value_percent, reverse=True)
        return bets

    def diff_odds(
        self, gid: int, current: LiveMatchSnapshot
    ) -> dict[str, tuple[float, float]]:
        """Считает разницу коэффициентов между текущим и прошлым снапшотом."""
        prev = self._last_snapshots.get(gid)
        if prev is None:
            return {}
        diffs: dict[str, tuple[float, float]] = {}
        for key, val in current.odds_map.items():
            old = prev.odds_map.get(key)
            if old is None or abs(val - old) < 1e-6:
                continue
            diffs[key] = (old, val)
        return diffs

    def remember(self, snap: LiveMatchSnapshot) -> None:
        self._last_snapshots[snap.game_id] = snap


def _flatten_odds(raw: Any) -> dict[str, float]:
    """Наивная распаковка live-odds в плоский словарь market_key→odd."""
    out: dict[str, float] = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict):
            continue
        market = row.get("market") or row.get("type") or row.get("name")
        price = row.get("price") or row.get("odds") or row.get("value")
        if market and price:
            try:
                out[str(market)] = float(price)
            except (TypeError, ValueError):
                continue
    return out


__all__ = ["LiveMatchSnapshot", "LiveMonitor"]
