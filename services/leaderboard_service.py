"""Глобальный лидерборд пользователей с ранжированием по нескольким
метрикам: hit_rate, ROI, streak, total_bets.

Используется в публичном /leaderboard и в админ-дашборде.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from services.user_stats import UserStats, UserStatsService


class LeaderboardMetric(str, Enum):
    HIT_RATE = "hit_rate"
    ROI = "roi"
    BEST_STREAK = "best_streak"
    TOTAL_BETS = "total_bets"
    AVG_ODDS = "avg_odds"
    AVG_VALUE = "avg_value"


@dataclass(slots=True)
class LeaderboardRow:
    rank: int
    tg_id: int
    display_name: str
    primary_metric: float
    hit_rate_pct: float
    roi_pct: float
    total_predictions: int
    settled: int
    best_streak: int


class LeaderboardService:
    def __init__(self, stats_service: UserStatsService) -> None:
        self._stats = stats_service
        self._names: dict[int, str] = {}

    def set_name(self, tg_id: int, display_name: str) -> None:
        self._names[tg_id] = display_name

    def compute(
        self,
        metric: LeaderboardMetric,
        *,
        min_settled: int = 10,
        limit: int = 20,
    ) -> list[LeaderboardRow]:
        rows: list[tuple[UserStats, float]] = []
        for tg_id in self._stats._per_user:
            s = self._stats.compute(tg_id)
            if s.settled < min_settled and metric is not LeaderboardMetric.TOTAL_BETS:
                continue
            val = self._primary(s, metric)
            rows.append((s, val))
        rows.sort(key=lambda r: r[1], reverse=True)
        output: list[LeaderboardRow] = []
        for rank, (s, val) in enumerate(rows[:limit], start=1):
            output.append(
                LeaderboardRow(
                    rank=rank,
                    tg_id=s.tg_id,
                    display_name=self._names.get(s.tg_id, f"User#{s.tg_id}"),
                    primary_metric=val,
                    hit_rate_pct=s.hit_rate_pct,
                    roi_pct=s.roi_pct,
                    total_predictions=s.total_predictions,
                    settled=s.settled,
                    best_streak=s.best_streak,
                )
            )
        return output

    @staticmethod
    def _primary(s: UserStats, metric: LeaderboardMetric) -> float:
        mapping = {
            LeaderboardMetric.HIT_RATE: s.hit_rate_pct,
            LeaderboardMetric.ROI: s.roi_pct,
            LeaderboardMetric.BEST_STREAK: float(s.best_streak),
            LeaderboardMetric.TOTAL_BETS: float(s.total_predictions),
            LeaderboardMetric.AVG_ODDS: s.avg_odds,
            LeaderboardMetric.AVG_VALUE: s.avg_value_pct,
        }
        return mapping.get(metric, 0.0)

    def rank_for_user(
        self,
        tg_id: int,
        metric: LeaderboardMetric,
        *,
        min_settled: int = 10,
    ) -> int | None:
        board = self.compute(metric, min_settled=min_settled, limit=10_000)
        for row in board:
            if row.tg_id == tg_id:
                return row.rank
        return None


__all__ = ["LeaderboardMetric", "LeaderboardRow", "LeaderboardService"]
