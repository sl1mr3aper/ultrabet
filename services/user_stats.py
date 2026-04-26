"""Персональная статистика пользователя: история его прогнозов, ROI, streak.

Используется в /stats_for_me и в панели админа.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean

from services.analytics import PredictionTick


@dataclass(slots=True)
class UserStats:
    tg_id: int
    total_predictions: int = 0
    settled: int = 0
    won: int = 0
    lost: int = 0
    hit_rate_pct: float = 0.0
    roi_pct: float = 0.0
    avg_odds: float = 0.0
    avg_value_pct: float = 0.0
    best_streak: int = 0
    worst_streak: int = 0
    favorite_market: str = ""
    favorite_league: str = ""
    markets_breakdown: dict[str, int] = field(default_factory=dict)
    last_prediction_at: datetime | None = None


class UserStatsService:
    """Хранит историю прогнозов per-user и вычисляет метрики."""

    def __init__(self) -> None:
        self._per_user: dict[int, list[PredictionTick]] = {}

    def record(self, tg_id: int, tick: PredictionTick) -> None:
        self._per_user.setdefault(tg_id, []).append(tick)

    def settle(
        self,
        tg_id: int,
        game_id: int,
        won_map: dict[str, bool],
    ) -> int:
        """Массово выставляет won для тикетов пользователя по game_id."""
        ticks = self._per_user.get(tg_id, [])
        updated = 0
        for t in ticks:
            if t.game_id == game_id and not t.settled:
                won = won_map.get(t.predicted_market)
                if won is not None:
                    t.settled = True
                    t.won = won
                    updated += 1
        return updated

    def compute(self, tg_id: int) -> UserStats:
        ticks = self._per_user.get(tg_id, [])
        stats = UserStats(tg_id=tg_id)
        stats.total_predictions = len(ticks)
        if not ticks:
            return stats
        stats.last_prediction_at = max(t.created_at for t in ticks)
        settled = [t for t in ticks if t.settled]
        stats.settled = len(settled)
        if settled:
            stats.won = sum(1 for t in settled if t.won is True)
            stats.lost = sum(1 for t in settled if t.won is False)
            stats.hit_rate_pct = stats.won / stats.settled * 100.0
            profit = sum(
                (t.actual_odds - 1.0 if t.won else -1.0) for t in settled
            )
            stats.roi_pct = profit / stats.settled * 100.0
        stats.avg_odds = mean(t.actual_odds for t in ticks)
        stats.avg_value_pct = mean(t.value_percent for t in ticks)

        # streaks
        cur = 0
        best = 0
        worst = 0
        cur_worst = 0
        for t in settled:
            if t.won is True:
                cur += 1
                cur_worst = 0
                best = max(best, cur)
            elif t.won is False:
                cur = 0
                cur_worst += 1
                worst = max(worst, cur_worst)
        stats.best_streak = best
        stats.worst_streak = worst

        # markets breakdown
        counter = Counter(t.predicted_market for t in ticks)
        stats.markets_breakdown = dict(counter.most_common(10))
        if stats.markets_breakdown:
            stats.favorite_market = next(iter(stats.markets_breakdown))
        return stats

    def leaderboard(self, *, min_settled: int = 10) -> list[UserStats]:
        """Топ пользователей по hit_rate (имеющих >= min_settled ставок)."""
        rows: list[UserStats] = []
        for tg_id in self._per_user:
            s = self.compute(tg_id)
            if s.settled >= min_settled:
                rows.append(s)
        rows.sort(key=lambda s: (s.hit_rate_pct, s.roi_pct), reverse=True)
        return rows

    def user_count(self) -> int:
        return len(self._per_user)

    def clear_user(self, tg_id: int) -> None:
        self._per_user.pop(tg_id, None)


__all__ = ["UserStats", "UserStatsService"]
