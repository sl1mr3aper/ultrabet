"""Тесты анализа формы."""

from __future__ import annotations

from core.form_analyzer import analyze_form


def _g(home_id: int, away_id: int, home: int, away: int) -> dict:
    return {
        "homeTeam": {"id": home_id},
        "awayTeam": {"id": away_id},
        "score": {"home": home, "away": away},
    }


def test_form_basic_wins():
    games = [
        _g(1, 2, 2, 1),
        _g(3, 1, 0, 1),
        _g(1, 4, 1, 1),
    ]
    f = analyze_form(team_id=1, games=games)
    assert f.wins == 2
    assert f.draws == 1
    assert f.losses == 0
    assert f.streak_repr == "WWD"
    assert f.points == 7


def test_form_avg_goals():
    games = [
        _g(1, 2, 2, 0),
        _g(2, 1, 0, 3),
    ]
    f = analyze_form(team_id=1, games=games)
    assert f.avg_goals_for == (2 + 3) / 2
    assert f.avg_goals_against == 0.0


def test_form_empty_input():
    f = analyze_form(team_id=1, games=[])
    assert f.games_count == 0
    assert f.weighted_score == 0.0


def test_form_skips_unrelated_games():
    games = [_g(99, 88, 2, 1)]
    f = analyze_form(team_id=1, games=games)
    assert f.games_count == 0


def test_form_weighted_recent_more_important():
    # 3 matches: last 2 won, oldest lost — weighted score должен быть высоким
    games = [
        _g(1, 2, 2, 0),
        _g(2, 1, 0, 1),
        _g(2, 1, 3, 0),  # oldest, loss for team 1
    ]
    f = analyze_form(team_id=1, games=games)
    assert f.weighted_score > 0.5
