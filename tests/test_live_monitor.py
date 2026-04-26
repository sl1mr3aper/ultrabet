"""Тесты LiveMonitor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.value_calculator import ValueCalculator
from services.live_monitor import LiveMatchSnapshot, LiveMonitor


@pytest.mark.asyncio
async def test_snapshot_empty():
    client = AsyncMock()
    client.list_games = AsyncMock(return_value=[])
    mon = LiveMonitor(client, value_calculator=ValueCalculator())
    out = await mon.snapshot()
    assert out == []


@pytest.mark.asyncio
async def test_snapshot_parses_basic_fields():
    client = AsyncMock()
    client.list_games = AsyncMock(
        return_value=[
            {
                "id": 42,
                "home_team": {"name": "A"},
                "away_team": {"name": "B"},
                "league": {"name": "L"},
                "minute": 23,
                "score": {"home": 1, "away": 0},
            }
        ]
    )
    client.get_live_odds = AsyncMock(
        return_value=[{"market": "home", "price": 2.0}]
    )
    mon = LiveMonitor(client, value_calculator=ValueCalculator())
    out = await mon.snapshot()
    assert len(out) == 1
    assert out[0].home_name == "A"
    assert out[0].minute == 23
    assert out[0].odds_map == {"home": 2.0}


def test_detect_value():
    snap = LiveMatchSnapshot(
        game_id=1,
        home_name="A",
        away_name="B",
        league_name="L",
        minute=30,
        home_score=0,
        away_score=0,
        odds_map={"home": 3.0, "away": 5.0},
    )
    mon = LiveMonitor(
        client=None,
        value_calculator=ValueCalculator(min_value_percent=2.0, min_probability=0.90),
        min_value_pct=5.0,
    )
    # home: p=0.95, кф=1.20 → 14% value (проходит фильтр p≥0.9, odds>1.15)
    snap.odds_map = {"home": 1.20, "away": 5.0}
    bets = mon.detect_value(snap, {"home": 0.95, "away": 0.10})
    assert len(bets) == 1
    assert bets[0].market_key == "home"


def test_diff_odds_tracks_changes():
    mon = LiveMonitor(client=None, value_calculator=ValueCalculator())
    s1 = LiveMatchSnapshot(
        game_id=1,
        home_name="A", away_name="B", league_name="L", minute=1,
        home_score=0, away_score=0,
        odds_map={"home": 2.0, "draw": 3.0},
    )
    mon.remember(s1)
    s2 = LiveMatchSnapshot(
        game_id=1,
        home_name="A", away_name="B", league_name="L", minute=5,
        home_score=1, away_score=0,
        odds_map={"home": 1.5, "draw": 3.5},
    )
    diffs = mon.diff_odds(1, s2)
    assert diffs["home"] == (2.0, 1.5)
    assert diffs["draw"] == (3.0, 3.5)


def test_diff_no_prev_snapshot():
    mon = LiveMonitor(client=None, value_calculator=ValueCalculator())
    snap = LiveMatchSnapshot(
        game_id=99, home_name="A", away_name="B",
        league_name="L", minute=0, home_score=0, away_score=0,
    )
    assert mon.diff_odds(99, snap) == {}
