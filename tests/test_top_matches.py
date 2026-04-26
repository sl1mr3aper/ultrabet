"""Тесты TopMatchesService."""

from __future__ import annotations

from services.top_matches import LEAGUE_PRESTIGE, TopMatchesService


def test_score_uses_prestige():
    game_a = {
        "id": 1,
        "homeTeam": {"name": "A", "rating": 1500},
        "awayTeam": {"name": "B", "rating": 1500},
        "season": {"league": {"name": "Premier League", "country": {"name": "England"}}},
    }
    game_b = {
        "id": 2,
        "homeTeam": {"name": "C", "rating": 1500},
        "awayTeam": {"name": "D", "rating": 1500},
        "season": {"league": {"name": "Random Cup", "country": {"name": "Belarus"}}},
    }
    a = TopMatchesService._score(game_a)
    b = TopMatchesService._score(game_b)
    assert a is not None and b is not None
    assert a.score > b.score


def test_score_handles_missing_data():
    g = {"id": 7, "homeTeam": {}, "awayTeam": {}, "season": {}}
    res = TopMatchesService._score(g)
    assert res is not None
    assert res.score > 0


def test_score_invalid_returns_none():
    assert TopMatchesService._score({"id": "no"}) is None


def test_score_uses_team_ratings():
    game_top = {
        "id": 1,
        "homeTeam": {"name": "T", "rating": 1900},
        "awayTeam": {"name": "T2", "rating": 1900},
        "season": {"league": {"name": "Premier League"}},
    }
    game_low = {
        "id": 2,
        "homeTeam": {"name": "L", "rating": 1300},
        "awayTeam": {"name": "L2", "rating": 1300},
        "season": {"league": {"name": "Premier League"}},
    }
    a = TopMatchesService._score(game_top)
    b = TopMatchesService._score(game_low)
    assert a is not None and b is not None
    assert a.score > b.score


def test_prestige_table_complete():
    assert "Premier League" in LEAGUE_PRESTIGE
    assert "UEFA Champions League" in LEAGUE_PRESTIGE
