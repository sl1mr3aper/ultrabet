"""Тесты analyze_form."""

from __future__ import annotations

from services.form_analyzer import analyze_form, compare_form, streak_emoji


def _game(home_id, away_id, hs, as_):
    return {
        "home_team": {"id": home_id},
        "away_team": {"id": away_id},
        "score": {"home": hs, "away": as_},
    }


def test_empty_form():
    s = analyze_form(1, "A", [])
    assert s.games == 0
    assert s.points == 0


def test_basic_form():
    team_id = 10
    games = [
        _game(10, 20, 2, 1),  # W
        _game(20, 10, 0, 1),  # W
        _game(10, 30, 1, 1),  # D
        _game(40, 10, 3, 0),  # L
    ]
    s = analyze_form(team_id, "T", games)
    assert s.games == 4
    assert s.wins == 2
    assert s.draws == 1
    assert s.losses == 1
    assert s.points == 2 * 3 + 1


def test_clean_sheets_counted():
    games = [_game(1, 2, 1, 0), _game(1, 2, 2, 0), _game(1, 2, 0, 0)]
    s = analyze_form(1, "T", games)
    assert s.clean_sheets == 3


def test_btts_games_counted():
    games = [_game(1, 2, 1, 1), _game(1, 2, 2, 2), _game(1, 2, 1, 0)]
    s = analyze_form(1, "T", games)
    assert s.btts_games == 2


def test_streak_chars():
    games = [_game(1, 2, 2, 0), _game(1, 2, 1, 1), _game(1, 2, 0, 3)]
    s = analyze_form(1, "T", games)
    assert s.streak == "WDL"


def test_points_per_game():
    games = [_game(1, 2, 1, 0), _game(1, 2, 2, 0)]
    s = analyze_form(1, "T", games)
    assert abs(s.points_per_game - 3.0) < 1e-9


def test_unknown_team_game_ignored():
    games = [_game(100, 200, 1, 0)]  # team 1 не участвует
    s = analyze_form(1, "T", games)
    assert s.games == 1
    assert s.wins == 0  # outcome ?


def test_compare_form():
    a = analyze_form(1, "Alpha", [_game(1, 2, 2, 0)])
    b = analyze_form(2, "Beta", [_game(2, 3, 1, 1)])
    cmp = compare_form(a, b)
    assert "attack" in cmp
    assert "Alpha" in cmp["attack"]
    assert "Beta" in cmp["attack"]


def test_streak_emoji():
    assert streak_emoji("WWD") == "🟢🟢🟡"
    assert streak_emoji("WWWWWW")[0] == "🟢"
    assert streak_emoji("") == ""
