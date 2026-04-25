"""Тесты корректировок точности на основе доп. данных SStats."""

from __future__ import annotations

from core.accuracy_boost import (
    AccuracyAdjustments,
    adjust_for_injuries,
    adjust_for_last_games,
    adjust_for_standings,
    merge_adjustments,
)


def test_no_injuries_no_change():
    adj = adjust_for_injuries(1, 2, [])
    assert adj.home_rating_delta == 0
    assert adj.away_rating_delta == 0
    assert adj.notes == []


def test_injuries_for_home_team():
    injuries = [
        {"team": {"id": 1}, "reason": "ACL injury"},
        {"team": {"id": 1}, "reason": "Hamstring"},
    ]
    adj = adjust_for_injuries(home_team_id=1, away_team_id=2, injuries=injuries)
    assert adj.home_rating_delta < 0
    assert adj.away_rating_delta == 0
    assert any("Травмы хозяев" in n for n in adj.notes)


def test_injuries_skip_unknown_team():
    injuries = [{"team": {"id": 999}, "reason": "muscle"}]
    adj = adjust_for_injuries(1, 2, injuries)
    assert adj.home_rating_delta == 0
    assert adj.away_rating_delta == 0


def test_severe_injury_bigger_penalty():
    a = adjust_for_injuries(1, 2, [{"team": {"id": 1}, "reason": "ACL operation"}])
    b = adjust_for_injuries(1, 2, [{"team": {"id": 1}, "reason": "Doubtful"}])
    assert a.home_rating_delta < b.home_rating_delta


def test_last_games_adjusts_xg():
    last = {
        "home": {"avgXgFor": 2.2, "avgXgAgainst": 0.9},
        "away": {"avgXgFor": 1.8, "avgXgAgainst": 1.5},
    }
    adj = adjust_for_last_games(last)
    assert adj.home_xg_factor != 1.0 or adj.away_xg_factor != 1.0


def test_last_games_empty():
    adj = adjust_for_last_games(None)
    assert adj.home_xg_factor == 1.0
    assert adj.away_xg_factor == 1.0


def test_standings_top_team_boost():
    table = {
        "standings": [
            {"team": {"id": 1}},  # 1st place
            {"team": {"id": 7}},
            {"team": {"id": 2}},  # 3rd place
        ]
    }
    adj = adjust_for_standings(home_team_id=1, away_team_id=2, season_table=table)
    assert adj.home_rating_delta > 0
    # 2 на 3 из 3 — ниже середины (1.5), значит штраф, отрицательный delta
    assert adj.away_rating_delta < 0


def test_standings_no_match():
    table = {"standings": [{"team": {"id": 99}}]}
    adj = adjust_for_standings(1, 2, table)
    assert adj.home_rating_delta == 0
    assert adj.away_rating_delta == 0


def test_merge_adjustments_sums():
    a = AccuracyAdjustments(home_rating_delta=10, away_rating_delta=-5, notes=["a"])
    b = AccuracyAdjustments(home_rating_delta=2, away_xg_factor=1.1, notes=["b"])
    out = merge_adjustments(a, b)
    assert out.home_rating_delta == 12
    assert out.away_rating_delta == -5
    assert out.away_xg_factor == 1.1
    assert out.notes == ["a", "b"]
