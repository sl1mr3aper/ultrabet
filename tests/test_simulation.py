"""Тесты Monte-Carlo симуляции."""

from __future__ import annotations

from services.simulation import compare_with_analytical, simulate


def test_simulate_zero_runs_returns_single():
    r = simulate(1.0, 1.0, n_runs=0, seed=42)
    assert r.n_runs == 1


def test_probabilities_sum_to_approx_100():
    r = simulate(1.5, 1.2, n_runs=3000, seed=42)
    total = r.home_win_pct + r.draw_pct + r.away_win_pct
    assert 99.0 <= total <= 101.0


def test_home_dominates_when_xg_higher():
    r = simulate(3.0, 0.5, n_runs=3000, seed=42)
    assert r.home_win_pct > r.away_win_pct


def test_away_dominates_when_xg_higher():
    r = simulate(0.5, 3.0, n_runs=3000, seed=42)
    assert r.away_win_pct > r.home_win_pct


def test_btts_higher_when_both_offensive():
    r_off = simulate(2.0, 2.0, n_runs=3000, seed=42)
    r_def = simulate(0.3, 0.3, n_runs=3000, seed=42)
    assert r_off.btts_pct > r_def.btts_pct


def test_over25_correlates_with_xg_sum():
    r_low = simulate(0.5, 0.5, n_runs=3000, seed=42)
    r_high = simulate(2.5, 2.5, n_runs=3000, seed=42)
    assert r_high.over_2_5_pct > r_low.over_2_5_pct


def test_score_distribution_non_empty():
    r = simulate(1.5, 1.0, n_runs=2000, seed=42)
    assert len(r.score_distribution) > 0


def test_mc_and_analytical_close():
    """MC должен быть близок к аналитическому Poisson."""
    diff = compare_with_analytical(1.5, 1.0, n_runs=5000, seed=123)
    assert abs(diff["home"]) < 5.0
    assert abs(diff["draw"]) < 5.0
    assert abs(diff["away"]) < 5.0
