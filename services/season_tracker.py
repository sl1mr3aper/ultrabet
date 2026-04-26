"""Трекер динамики команд по сезону.

Сохраняет точки "позиция в таблице в неделю N" для каждой команды, считает
тренд (улучшается/ухудшается). Используется в prediction boost.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(slots=True)
class StandingsPoint:
    team_id: int
    team_name: str
    league_id: int
    season: str
    week: int
    position: int
    points: int
    played: int
    snapshot_date: date


@dataclass(slots=True)
class TeamSeasonTrend:
    team_id: int
    team_name: str
    current_position: int
    current_points: int
    position_trend: int  # +N = вверх, -N = вниз за последние 4 недели
    points_trend: int
    history: list[StandingsPoint] = field(default_factory=list)


class SeasonTracker:
    def __init__(self) -> None:
        self._points: dict[tuple[int, str], list[StandingsPoint]] = defaultdict(list)

    def record(self, point: StandingsPoint) -> None:
        key = (point.team_id, point.season)
        self._points[key].append(point)
        self._points[key].sort(key=lambda p: (p.week, p.snapshot_date))

    def trend(
        self, team_id: int, season: str, *, lookback_weeks: int = 4
    ) -> TeamSeasonTrend | None:
        key = (team_id, season)
        points = self._points.get(key)
        if not points:
            return None
        latest = points[-1]
        # Найти "старую" точку на lookback_weeks назад
        target_week = max(1, latest.week - lookback_weeks)
        old = next(
            (p for p in points if p.week == target_week),
            points[0],
        )
        return TeamSeasonTrend(
            team_id=team_id,
            team_name=latest.team_name,
            current_position=latest.position,
            current_points=latest.points,
            position_trend=old.position - latest.position,
            points_trend=latest.points - old.points,
            history=list(points[-lookback_weeks:]),
        )

    def leaders(self, league_id: int, season: str, *, top_n: int = 5) -> list[StandingsPoint]:
        """Возвращает последние точки команд в этой лиге, отсортированных по position."""
        latest_per_team: dict[int, StandingsPoint] = {}
        for key, points in self._points.items():
            _, s = key
            if s != season:
                continue
            if not points:
                continue
            last = points[-1]
            if last.league_id != league_id:
                continue
            latest_per_team[last.team_id] = last
        sorted_points = sorted(
            latest_per_team.values(), key=lambda p: (p.position, -p.points)
        )
        return sorted_points[:top_n]

    def streakers(
        self, season: str, *, min_position_improve: int = 3
    ) -> list[TeamSeasonTrend]:
        """Команды, поднявшиеся не менее чем на N позиций за 4 недели."""
        out: list[TeamSeasonTrend] = []
        for key in self._points:
            team_id, s = key
            if s != season:
                continue
            trend = self.trend(team_id, s)
            if trend is not None and trend.position_trend >= min_position_improve:
                out.append(trend)
        out.sort(key=lambda t: t.position_trend, reverse=True)
        return out

    def fallers(
        self, season: str, *, min_position_drop: int = 3
    ) -> list[TeamSeasonTrend]:
        out: list[TeamSeasonTrend] = []
        for key in self._points:
            team_id, s = key
            if s != season:
                continue
            trend = self.trend(team_id, s)
            if trend is not None and trend.position_trend <= -min_position_drop:
                out.append(trend)
        out.sort(key=lambda t: t.position_trend)
        return out

    def teams_in_season(self, season: str) -> list[int]:
        return sorted({k[0] for k in self._points if k[1] == season})


def _example_points() -> list[StandingsPoint]:
    """Для тестов."""
    return [
        StandingsPoint(
            team_id=1,
            team_name="Alpha",
            league_id=10,
            season="2024/25",
            week=w,
            position=10 - w,  # улучшается
            points=w * 3,
            played=w,
            snapshot_date=date.today() - timedelta(days=(8 - w) * 7),
        )
        for w in range(1, 9)
    ]


__all__ = ["SeasonTracker", "StandingsPoint", "TeamSeasonTrend"]
