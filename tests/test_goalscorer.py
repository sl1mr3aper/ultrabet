"""Тесты goalscorer."""

from __future__ import annotations

from services.goalscorer import best_pick, compute, rank_top_scorers


def test_compute_zero_lambda():
    s = compute({"name": "A", "goals_per_90": 0, "minutes_played": 90})
    assert s.p_score == 0.0
    assert s.lambda_match == 0.0


def test_compute_lambda_math():
    s = compute({"name": "A", "goals_per_90": 1.0, "minutes_played": 90})
    assert abs(s.lambda_match - 1.0) < 1e-9
    # P(score) = 1 - e^-1 ≈ 0.6321
    assert abs(s.p_score - 0.6321205588) < 1e-6


def test_minutes_scaling():
    full = compute({"name": "A", "goals_per_90": 1.0, "minutes_played": 90})
    half = compute({"name": "A", "goals_per_90": 1.0, "minutes_played": 45})
    assert half.p_score < full.p_score


def test_brace_and_hattrick_decrease():
    s = compute({"name": "A", "goals_per_90": 1.0, "minutes_played": 90})
    assert s.p_brace < s.p_score
    assert s.p_hattrick < s.p_brace


def test_rank_by_p_score():
    players = [
        {"name": "low", "goals_per_90": 0.1, "minutes_played": 90, "id": 1},
        {"name": "high", "goals_per_90": 1.5, "minutes_played": 90, "id": 2},
        {"name": "mid", "goals_per_90": 0.5, "minutes_played": 90, "id": 3},
    ]
    ranked = rank_top_scorers(players)
    assert ranked[0].player_name == "high"
    assert ranked[-1].player_name == "low"


def test_rank_limit():
    players = [
        {"name": f"p{i}", "goals_per_90": 0.5, "minutes_played": 90, "id": i}
        for i in range(20)
    ]
    assert len(rank_top_scorers(players, limit=5)) == 5


def test_best_pick_identifies_value():
    scorers = rank_top_scorers(
        [
            {"name": "alpha", "goals_per_90": 0.7, "minutes_played": 90, "id": 1},
            {"name": "beta", "goals_per_90": 0.3, "minutes_played": 90, "id": 2},
        ]
    )
    odds = {"alpha": 2.5, "beta": 3.5}
    pick = best_pick(scorers, odds)
    assert pick is not None
    name = pick[0].player_name
    assert name in {"alpha", "beta"}


def test_best_pick_no_odds():
    scorers = rank_top_scorers(
        [{"name": "x", "goals_per_90": 1.0, "minutes_played": 90, "id": 1}]
    )
    assert best_pick(scorers, {}) is None
