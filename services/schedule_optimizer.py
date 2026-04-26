"""Оптимизатор расписания обновления данных.

По нагрузке API и паттернам чтения находит оптимальные ttl для кэша
и частоту polling-а live-матчей, чтобы не упереться в rate limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(slots=True)
class RefreshPlan:
    leagues_ttl_hours: float
    games_list_ttl_minutes: float
    game_detail_ttl_minutes: float
    prematch_odds_ttl_minutes: float
    live_odds_ttl_seconds: float
    injuries_ttl_hours: float
    standings_ttl_hours: float
    last_games_stats_ttl_hours: float
    total_api_calls_per_day: int
    safety_margin_percent: float


class ScheduleOptimizer:
    def __init__(self, *, daily_budget: int = 100) -> None:
        self._daily_budget = daily_budget

    def plan(
        self,
        *,
        active_leagues: int = 5,
        upcoming_matches: int = 30,
        live_matches: int = 5,
        daily_user_requests: int = 500,
    ) -> RefreshPlan:
        # Оценим количество API-вызовов в день для каждого типа данных
        # и подгоним ttl, чтобы уложиться в budget с запасом 20%.
        safety_margin = 20.0
        budget = int(self._daily_budget * (100 - safety_margin) / 100)

        # Приоритет: live > game detail > prematch odds > leagues > standings
        calls_live_per_match = max(1, 86400 / 60)  # раз в минуту
        calls_game_detail = max(1, daily_user_requests / 10)
        calls_prematch = max(upcoming_matches * 4, 30)
        calls_leagues = 1
        calls_standings = active_leagues
        calls_last_games = upcoming_matches * 2
        calls_injuries = upcoming_matches

        total_naive = (
            calls_live_per_match * live_matches
            + calls_game_detail
            + calls_prematch
            + calls_leagues
            + calls_standings
            + calls_last_games
            + calls_injuries
        )

        if total_naive > budget:
            scale = total_naive / budget
        else:
            scale = 1.0

        return RefreshPlan(
            leagues_ttl_hours=24.0,
            games_list_ttl_minutes=5.0 * scale,
            game_detail_ttl_minutes=10.0 * scale,
            prematch_odds_ttl_minutes=5.0 * scale,
            live_odds_ttl_seconds=15.0 * scale,
            injuries_ttl_hours=6.0 * scale,
            standings_ttl_hours=12.0 * scale,
            last_games_stats_ttl_hours=24.0,
            total_api_calls_per_day=int(total_naive / scale),
            safety_margin_percent=safety_margin,
        )

    def recommend_live_poll_interval(
        self, *, live_matches: int, daily_budget_used_so_far: int
    ) -> int:
        """Рекомендованный интервал polling-а live-матчей в секундах."""
        remaining = max(0, self._daily_budget - daily_budget_used_so_far)
        seconds_left = max(1, 86400 - datetime.utcnow().hour * 3600)
        if live_matches == 0 or remaining == 0:
            return 60
        # на каждый live-матч сколько запросов в секунду можем себе позволить
        per_second = remaining / seconds_left / max(1, live_matches)
        if per_second <= 0:
            return 120
        return max(10, int(1.0 / per_second))

    def should_refresh(
        self,
        *,
        last_refresh: datetime,
        ttl: timedelta,
    ) -> bool:
        return datetime.utcnow() - last_refresh >= ttl


__all__ = ["RefreshPlan", "ScheduleOptimizer"]
