"""Smoke-тесты CSV-экспорта."""
from __future__ import annotations

import csv
import io

from services.csv_export import render_match_csv


def test_render_match_csv_flattens_nested_structures():
    bundle = {
        "game": {
            "id": 12345,
            "home": {"name": "Team A", "rating": 1500.5},
            "away": {"name": "Team B", "rating": 1450.0},
            "score": None,
        },
        "odds": [
            {"book": "Bet365", "value": 2.10},
            {"book": "Pinnacle", "value": 2.05},
        ],
        "summary": "match preview text",
    }
    payload = render_match_csv(bundle)
    text = payload.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header, *data = rows
    assert header == ["section", "key", "value"]
    sections = {row[0] for row in data}
    assert {"game", "odds", "summary"}.issubset(sections)
    keys = {(row[0], row[1]) for row in data}
    assert ("game", "id") in keys
    assert ("game", "home.name") in keys
    assert ("game", "home.rating") in keys
    assert ("odds", "[0].book") in keys
    assert ("odds", "[1].value") in keys


def test_render_match_csv_handles_empty_and_none():
    bundle = {
        "game": None,
        "odds": [],
        "extra": {},
    }
    payload = render_match_csv(bundle)
    text = payload.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["section", "key", "value"]
    # Должен быть хотя бы один служебный маркер пустых коллекций.
    body = {(r[0], r[1], r[2]) for r in rows[1:]}
    assert ("odds", "", "[]") in body or ("odds", "", "") in body
