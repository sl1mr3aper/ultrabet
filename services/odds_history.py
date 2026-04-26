"""Хранилище истории коэффициентов для matching line movements.

Используется:
- детекция резких скачков коэффициентов (sharp money signals).
- построение графика движения коэффициента по времени для /odds_history.
- вычисление средневзвешенной цены за последние N часов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(slots=True)
class OddsSnapshot:
    game_id: int
    market: str
    bookmaker: str
    odds: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class OddsSeries:
    game_id: int
    market: str
    bookmaker: str
    snapshots: list[OddsSnapshot] = field(default_factory=list)

    def add(self, odds: float, *, timestamp: datetime | None = None) -> None:
        self.snapshots.append(
            OddsSnapshot(
                game_id=self.game_id,
                market=self.market,
                bookmaker=self.bookmaker,
                odds=odds,
                timestamp=timestamp or datetime.utcnow(),
            )
        )

    def latest(self) -> float | None:
        return self.snapshots[-1].odds if self.snapshots else None

    def earliest(self) -> float | None:
        return self.snapshots[0].odds if self.snapshots else None

    def drift(self) -> float:
        """Разница (latest - earliest) в процентах."""
        if len(self.snapshots) < 2:
            return 0.0
        start = self.snapshots[0].odds
        end = self.snapshots[-1].odds
        if start <= 0:
            return 0.0
        return (end - start) / start * 100.0

    def max_drop(self) -> float:
        """Максимальное падение коэфа (%) от локального пика."""
        if len(self.snapshots) < 2:
            return 0.0
        peak = self.snapshots[0].odds
        worst = 0.0
        for s in self.snapshots:
            if s.odds > peak:
                peak = s.odds
            drop = (peak - s.odds) / peak * 100.0 if peak > 0 else 0.0
            if drop > worst:
                worst = drop
        return worst

    def average(self) -> float:
        if not self.snapshots:
            return 0.0
        return sum(s.odds for s in self.snapshots) / len(self.snapshots)

    def last_n_minutes(self, minutes: int) -> list[OddsSnapshot]:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return [s for s in self.snapshots if s.timestamp >= cutoff]


class OddsHistoryStore:
    def __init__(self) -> None:
        self._series: dict[tuple[int, str, str], OddsSeries] = {}

    def _key(self, game_id: int, market: str, bookmaker: str) -> tuple[int, str, str]:
        return (game_id, market, bookmaker)

    def record(
        self,
        *,
        game_id: int,
        market: str,
        bookmaker: str,
        odds: float,
        timestamp: datetime | None = None,
    ) -> OddsSeries:
        key = self._key(game_id, market, bookmaker)
        series = self._series.get(key)
        if series is None:
            series = OddsSeries(
                game_id=game_id, market=market, bookmaker=bookmaker
            )
            self._series[key] = series
        series.add(odds, timestamp=timestamp)
        return series

    def get(self, game_id: int, market: str, bookmaker: str) -> OddsSeries | None:
        return self._series.get(self._key(game_id, market, bookmaker))

    def all_series_for_game(self, game_id: int) -> list[OddsSeries]:
        return [s for k, s in self._series.items() if k[0] == game_id]

    def sharp_movers(self, *, min_drift_pct: float = 10.0) -> list[OddsSeries]:
        """Возвращает series с сильным движением."""
        return [s for s in self._series.values() if abs(s.drift()) >= min_drift_pct]

    def clear_game(self, game_id: int) -> int:
        keys_to_del = [k for k in self._series if k[0] == game_id]
        for k in keys_to_del:
            del self._series[k]
        return len(keys_to_del)


__all__ = ["OddsHistoryStore", "OddsSeries", "OddsSnapshot"]
