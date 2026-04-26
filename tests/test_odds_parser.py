"""Тесты парсера коэффициентов SStats."""

from __future__ import annotations

from core.markets import MarketKey
from services.odds_parser import OddsParser


def _build_raw_odds() -> list[dict]:
    return [
        {
            "bookmakerName": "Pinnacle",
            "odds": [
                {
                    "marketName": "Match Winner",
                    "odds": [
                        {"name": "Home", "value": 2.10},
                        {"name": "Draw", "value": 3.40},
                        {"name": "Away", "value": 3.20},
                    ],
                },
                {
                    "marketName": "Goals Over/Under",
                    "odds": [
                        {"name": "Over 2.5", "value": 1.95},
                        {"name": "Under 2.5", "value": 1.85},
                    ],
                },
                {
                    "marketName": "Both Teams To Score",
                    "odds": [
                        {"name": "Yes", "value": 1.70},
                        {"name": "No", "value": 2.10},
                    ],
                },
            ],
        }
    ]


def test_parse_match_winner():
    parser = OddsParser()
    parsed = parser.parse(_build_raw_odds())
    assert parsed[MarketKey.HOME] == 2.10
    assert parsed[MarketKey.DRAW] == 3.40
    assert parsed[MarketKey.AWAY] == 3.20


def test_parse_overunder():
    parser = OddsParser()
    parsed = parser.parse(_build_raw_odds())
    assert parsed[MarketKey.OVER_25] == 1.95
    assert parsed[MarketKey.UNDER_25] == 1.85


def test_parse_btts():
    parser = OddsParser()
    parsed = parser.parse(_build_raw_odds())
    assert parsed[MarketKey.BTTS_YES] == 1.70
    assert parsed[MarketKey.BTTS_NO] == 2.10


def test_best_per_market():
    raw = [
        {
            "bookmakerName": "Book1",
            "odds": [
                {
                    "marketName": "Match Winner",
                    "odds": [{"name": "Home", "value": 2.05}],
                }
            ],
        },
        {
            "bookmakerName": "Book2",
            "odds": [
                {
                    "marketName": "Match Winner",
                    "odds": [{"name": "Home", "value": 2.20}],
                }
            ],
        },
    ]
    parser = OddsParser()
    best = parser.best_per_market(raw)
    assert best[MarketKey.HOME] == (2.20, "Book2")


def test_empty_input():
    parser = OddsParser()
    assert parser.parse(None) == {}
    assert parser.parse([]) == {}
