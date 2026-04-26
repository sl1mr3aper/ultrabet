"""Тесты league_power."""

from __future__ import annotations

from services.league_power import compute_league_stats, normalize_xg


def test_empty_league():
    s = compute_league_stats(1, "L", "C", [])
    assert s.matches_played == 0
    assert s.avg_total_goals == 0


def test_basic_league():
    games = [
        {"home_score": 2, "away_score": 1},
        {"home_score": 0, "away_score": 0},
        {"home_score": 1, "away_score": 1},
        {"home_score": 3, "away_score": 2},
    ]
    s = compute_league_stats(1, "L", "C", games)
    assert s.matches_played == 4
    assert s.avg_goals_home == 1.5
    assert s.avg_goals_away == 1.0
    assert abs(s.avg_total_goals - 2.5) < 1e-9
    assert s.home_win_pct == 50.0
    assert s.draw_pct == 50.0
    assert s.btts_pct == 75.0


def test_normalize_xg_identity():
    assert abs(normalize_xg(1.5, 1.35) - 1.5) < 1e-9


def test_normalize_xg_scales():
    # Лига с очень малым средним тоталом → xG растягивается вверх
    out = normalize_xg(1.0, 1.0)  # league_avg=1.0, base=1.35 → 1.35
    assert abs(out - 1.35) < 1e-9


def test_normalize_xg_zero_avg_returns_original():
    assert normalize_xg(2.0, 0) == 2.0
