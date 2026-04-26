"""Тесты ансамбля."""

from __future__ import annotations

import math

from core.ensemble import build_predictions
from core.markets import MarketKey


def test_build_predictions_main_three_sum_to_one():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    s = (
        payload.probabilities[MarketKey.HOME]
        + payload.probabilities[MarketKey.DRAW]
        + payload.probabilities[MarketKey.AWAY]
    )
    assert math.isclose(s, 1.0, abs_tol=1e-3)


def test_double_chance_makes_sense():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    p1x = payload.probabilities[MarketKey.DOUBLE_1X]
    p_h = payload.probabilities[MarketKey.HOME]
    p_d = payload.probabilities[MarketKey.DRAW]
    assert math.isclose(p1x, min(p_h + p_d, 0.999), abs_tol=1e-3)


def test_btts_pair_complementary():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    yes = payload.probabilities[MarketKey.BTTS_YES]
    no = payload.probabilities[MarketKey.BTTS_NO]
    assert math.isclose(yes + no, 1.0, abs_tol=1e-3)


def test_overunder_pairs_complementary():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    for over_key, under_key in (
        (MarketKey.OVER_15, MarketKey.UNDER_15),
        (MarketKey.OVER_25, MarketKey.UNDER_25),
        (MarketKey.OVER_35, MarketKey.UNDER_35),
    ):
        s = payload.probabilities[over_key] + payload.probabilities[under_key]
        assert math.isclose(s, 1.0, abs_tol=1e-3)


def test_team_total_pairs_complementary():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    s = payload.probabilities[MarketKey.HOME_OVER_15] + payload.probabilities[MarketKey.HOME_UNDER_15]
    assert math.isclose(s, 1.0, abs_tol=1e-3)


def test_top_scores_present():
    payload = build_predictions(home_rating=1500, away_rating=1500)
    assert payload.top_scores
    assert len(payload.top_scores) == 5
