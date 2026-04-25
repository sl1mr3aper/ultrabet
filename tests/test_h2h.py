"""Тесты H2H."""

from __future__ import annotations

from services.h2h_service import H2HMatch, H2HService


def test_winner_detection():
    m = H2HMatch(1, "2024-01-01", "A", "B", 2, 1, "L")
    assert m.winner == "home"
    m2 = H2HMatch(2, "2024-01-02", "A", "B", 0, 1, "L")
    assert m2.winner == "away"
    m3 = H2HMatch(3, "2024-01-03", "A", "B", 1, 1, "L")
    assert m3.winner == "draw"
    m4 = H2HMatch(4, "2024-01-04", "A", "B", None, None, None)
    assert m4.winner is None


def test_row_parsing_basic():
    raw = {
        "id": 5,
        "homeTeam": {"name": "Home"},
        "awayTeam": {"name": "Away"},
        "score": {"home": 2, "away": 1},
        "season": {"league": {"name": "Friendly"}},
        "date": "2024-01-01T00:00:00Z",
    }
    parsed = H2HService._row_to_match(raw)
    assert parsed is not None
    assert parsed.game_id == 5
    assert parsed.home_score == 2
    assert parsed.league_name == "Friendly"


def test_row_parsing_invalid_id():
    assert H2HService._row_to_match({"id": "x"}) is None


def test_row_parsing_missing_score():
    raw = {"id": 7, "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}}
    parsed = H2HService._row_to_match(raw)
    assert parsed is not None
    assert parsed.home_score is None
