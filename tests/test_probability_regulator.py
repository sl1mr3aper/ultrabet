"""Smoke-тесты Probability Regulator."""
from __future__ import annotations

from core.market_evaluator import evaluate_market
from core.probability_regulator import (
    HistoricalRow,
    aggregate_feedback,
    regulate,
)


def test_evaluate_market_1x2():
    assert evaluate_market("1", 2, 0) is True
    assert evaluate_market("X", 1, 1) is True
    assert evaluate_market("2", 0, 3) is True
    assert evaluate_market("12", 1, 0) is True
    assert evaluate_market("12", 1, 1) is False


def test_evaluate_market_totals():
    assert evaluate_market("O25", 2, 1) is True
    assert evaluate_market("U25", 1, 1) is True
    assert evaluate_market("BTTS", 1, 1) is True
    assert evaluate_market("BTTS", 2, 0) is False


def test_regulate_with_history_shifts_probability():
    # Модель: TB 2.5 = 50%. История лиги: 30 матчей, в 24 из них пробил TB 2.5.
    history = [HistoricalRow(home_score=2, away_score=2)] * 24 + [
        HistoricalRow(home_score=1, away_score=1)
    ] * 6
    res = regulate({"O25": 0.50}, history)
    assert "O25" in res
    r = res["O25"]
    # должен сдвинуться вверх (фактический hit-rate ~80%)
    assert r.p_corrected > 0.55
    assert r.delta_pp > 0
    assert r.hist_games == 30


def test_regulate_no_history_returns_model_probabilities():
    res = regulate({"O25": 0.50}, history=[])
    assert res["O25"].p_corrected == 0.50
    assert res["O25"].hist_games == 0


def test_aggregate_feedback_counts_hits_and_games():
    rows = [
        ("O25", True),
        ("O25", True),
        ("O25", False),
        ("O25", None),  # игнорируется
        ("BTTS", True),
    ]
    agg = aggregate_feedback(rows)
    assert agg["O25"] == (2, 3)
    assert agg["BTTS"] == (1, 1)
