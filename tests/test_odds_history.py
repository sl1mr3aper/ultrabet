"""Тесты odds_history."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.odds_history import OddsHistoryStore, OddsSeries


def test_record_creates_series():
    store = OddsHistoryStore()
    series = store.record(game_id=1, market="home", bookmaker="bet365", odds=2.0)
    assert isinstance(series, OddsSeries)
    assert len(series.snapshots) == 1


def test_record_appends_to_existing():
    store = OddsHistoryStore()
    store.record(game_id=1, market="home", bookmaker="bet365", odds=2.0)
    store.record(game_id=1, market="home", bookmaker="bet365", odds=1.9)
    series = store.get(1, "home", "bet365")
    assert len(series.snapshots) == 2


def test_drift_positive():
    store = OddsHistoryStore()
    store.record(game_id=1, market="home", bookmaker="bet", odds=2.0)
    store.record(game_id=1, market="home", bookmaker="bet", odds=2.2)
    series = store.get(1, "home", "bet")
    assert abs(series.drift() - 10.0) < 1e-9


def test_drift_negative():
    store = OddsHistoryStore()
    store.record(game_id=1, market="home", bookmaker="bet", odds=2.0)
    store.record(game_id=1, market="home", bookmaker="bet", odds=1.8)
    series = store.get(1, "home", "bet")
    assert abs(series.drift() + 10.0) < 1e-9


def test_drift_single_snapshot_zero():
    store = OddsHistoryStore()
    store.record(game_id=1, market="h", bookmaker="b", odds=2.0)
    s = store.get(1, "h", "b")
    assert s.drift() == 0.0


def test_max_drop():
    store = OddsHistoryStore()
    for o in [2.0, 2.2, 2.1, 1.8, 1.9]:
        store.record(game_id=1, market="h", bookmaker="b", odds=o)
    s = store.get(1, "h", "b")
    # peak 2.2, valley 1.8 → drop (2.2-1.8)/2.2 ≈ 18.18%
    assert abs(s.max_drop() - 18.1818) < 0.01


def test_latest_and_earliest():
    store = OddsHistoryStore()
    for o in [2.0, 2.1, 2.2]:
        store.record(game_id=1, market="h", bookmaker="b", odds=o)
    s = store.get(1, "h", "b")
    assert s.earliest() == 2.0
    assert s.latest() == 2.2


def test_average():
    store = OddsHistoryStore()
    for o in [2.0, 2.0, 2.0]:
        store.record(game_id=1, market="h", bookmaker="b", odds=o)
    s = store.get(1, "h", "b")
    assert s.average() == 2.0


def test_sharp_movers():
    store = OddsHistoryStore()
    store.record(game_id=1, market="h", bookmaker="b", odds=2.0)
    store.record(game_id=1, market="h", bookmaker="b", odds=2.4)  # +20%
    store.record(game_id=2, market="a", bookmaker="b", odds=1.5)
    store.record(game_id=2, market="a", bookmaker="b", odds=1.51)  # +0.66%
    sharp = store.sharp_movers(min_drift_pct=10.0)
    assert len(sharp) == 1
    assert sharp[0].game_id == 1


def test_clear_game():
    store = OddsHistoryStore()
    store.record(game_id=1, market="h", bookmaker="b", odds=2.0)
    store.record(game_id=1, market="a", bookmaker="b", odds=3.0)
    store.record(game_id=2, market="h", bookmaker="b", odds=2.0)
    removed = store.clear_game(1)
    assert removed == 2
    assert store.get(1, "h", "b") is None
    assert store.get(2, "h", "b") is not None


def test_last_n_minutes():
    store = OddsHistoryStore()
    now = datetime.utcnow()
    store.record(
        game_id=1, market="h", bookmaker="b", odds=2.0,
        timestamp=now - timedelta(minutes=60),
    )
    store.record(
        game_id=1, market="h", bookmaker="b", odds=2.1,
        timestamp=now - timedelta(minutes=5),
    )
    s = store.get(1, "h", "b")
    recent = s.last_n_minutes(10)
    assert len(recent) == 1
    assert recent[0].odds == 2.1
