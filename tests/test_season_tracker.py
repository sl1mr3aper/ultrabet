"""Тесты SeasonTracker."""

from __future__ import annotations

from datetime import date

from services.season_tracker import SeasonTracker, StandingsPoint


def _point(team_id, week, position, points, season="2024/25", league_id=10, team_name="T"):
    return StandingsPoint(
        team_id=team_id,
        team_name=team_name,
        league_id=league_id,
        season=season,
        week=week,
        position=position,
        points=points,
        played=week,
        snapshot_date=date.today(),
    )


def test_empty_tracker():
    t = SeasonTracker()
    assert t.trend(1, "2024/25") is None


def test_record_and_trend_improving():
    t = SeasonTracker()
    for w, pos in enumerate([10, 8, 6, 4, 2], start=1):
        t.record(_point(1, w, pos, w * 3))
    tr = t.trend(1, "2024/25")
    assert tr is not None
    assert tr.current_position == 2
    # Week 5 vs week 1: 10 - 2 = +8 (поднялся)
    assert tr.position_trend == 8


def test_trend_declining():
    t = SeasonTracker()
    for w, pos in enumerate([2, 4, 6, 8, 10], start=1):
        t.record(_point(1, w, pos, w))
    tr = t.trend(1, "2024/25")
    # 2 - 10 = -8 (упал)
    assert tr.position_trend == -8


def test_leaders():
    t = SeasonTracker()
    t.record(_point(1, 1, 1, 30, team_name="A"))
    t.record(_point(2, 1, 2, 25, team_name="B"))
    t.record(_point(3, 1, 3, 20, team_name="C"))
    t.record(_point(4, 1, 4, 15, team_name="D"))
    leaders = t.leaders(10, "2024/25", top_n=3)
    assert [l.team_name for l in leaders] == ["A", "B", "C"]


def test_streakers():
    t = SeasonTracker()
    # Team 1 — поднимается
    for w, pos in enumerate([10, 9, 8, 7, 6], start=1):
        t.record(_point(1, w, pos, w, team_name="Riser"))
    # Team 2 — стабилен
    for w in range(1, 6):
        t.record(_point(2, w, 5, 10, team_name="Stable"))
    streakers = t.streakers("2024/25", min_position_improve=3)
    assert len(streakers) == 1
    assert streakers[0].team_name == "Riser"


def test_fallers():
    t = SeasonTracker()
    # Team 1 — падает
    for w, pos in enumerate([1, 3, 5, 7, 9], start=1):
        t.record(_point(1, w, pos, w, team_name="Faller"))
    fallers = t.fallers("2024/25", min_position_drop=3)
    assert len(fallers) == 1
    assert fallers[0].team_name == "Faller"
    assert fallers[0].position_trend == -8


def test_teams_in_season():
    t = SeasonTracker()
    t.record(_point(1, 1, 1, 3))
    t.record(_point(2, 1, 2, 2))
    t.record(_point(3, 1, 1, 3, season="2023/24"))
    assert t.teams_in_season("2024/25") == [1, 2]


def test_trend_with_single_point():
    t = SeasonTracker()
    t.record(_point(1, 5, 3, 15))
    tr = t.trend(1, "2024/25")
    assert tr is not None
    assert tr.current_position == 3
    assert tr.position_trend == 0  # single point, no history
