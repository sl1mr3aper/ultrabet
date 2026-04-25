"""Тесты вспомогательных функций MatchFinder."""

from __future__ import annotations

from datetime import UTC, datetime

from services.match_finder import _candidate_from_raw, _parse_date


def test_parse_date_iso():
    dt = _parse_date("2025-05-01T20:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_date_unix():
    dt = _parse_date(1700000000)
    assert dt is not None
    assert dt == datetime.fromtimestamp(1700000000, tz=UTC)


def test_parse_date_invalid():
    assert _parse_date(None) is None
    assert _parse_date("garbage") is None


def test_candidate_from_raw_basic():
    raw = {
        "id": 7,
        "homeTeam": {"id": 1, "name": "Home"},
        "awayTeam": {"id": 2, "name": "Away"},
        "season": {
            "league": {
                "name": "Test League",
                "country": {"name": "Spain"},
            }
        },
        "date": "2025-05-01T20:00:00Z",
        "status": 1,
    }
    cand = _candidate_from_raw(raw)
    assert cand is not None
    assert cand.game_id == 7
    assert cand.home_id == 1
    assert cand.away_name == "Away"
    assert cand.league_country == "Spain"


def test_candidate_from_raw_invalid():
    assert _candidate_from_raw({"id": "not-int"}) is None
