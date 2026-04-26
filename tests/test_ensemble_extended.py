"""Дополнительные тесты ансамбля для расширенных рынков."""

from __future__ import annotations

from core.ensemble import build_predictions
from core.markets import MarketKey


def test_extended_markets_present():
    p = build_predictions(home_rating=1700, away_rating=1500)
    keys = set(p.probabilities.keys())
    expected = {
        MarketKey.OVER_05,
        MarketKey.UNDER_05,
        MarketKey.OVER_55,
        MarketKey.UNDER_55,
        MarketKey.HOME_OVER_25,
        MarketKey.HOME_UNDER_25,
        MarketKey.AWAY_OVER_25,
        MarketKey.AWAY_UNDER_25,
        MarketKey.HANDICAP_HOME_PLUS_25,
        MarketKey.HANDICAP_HOME_MINUS_25,
        MarketKey.HANDICAP_AWAY_PLUS_25,
        MarketKey.HANDICAP_AWAY_MINUS_25,
        MarketKey.DNB_HOME,
        MarketKey.DNB_AWAY,
    }
    assert expected.issubset(keys)


def test_dnb_normalization():
    p = build_predictions(home_rating=1700, away_rating=1500)
    s = p.probabilities[MarketKey.DNB_HOME] + p.probabilities[MarketKey.DNB_AWAY]
    assert abs(s - 1.0) < 0.01


def test_over_under_05_pair_sums_to_one():
    p = build_predictions(home_rating=1500, away_rating=1500)
    s = p.probabilities[MarketKey.OVER_05] + p.probabilities[MarketKey.UNDER_05]
    assert abs(s - 1.0) < 0.01


def test_high_xg_increases_over_55():
    p_high = build_predictions(
        home_rating=2000, away_rating=2000,
        home_xg_api=3.0, away_xg_api=3.0,
    )
    p_low = build_predictions(
        home_rating=1500, away_rating=1500,
        home_xg_api=0.6, away_xg_api=0.6,
    )
    assert p_high.probabilities[MarketKey.OVER_55] > p_low.probabilities[MarketKey.OVER_55]


def test_handicap_25_lower_than_15_for_underdog():
    p = build_predictions(home_rating=1700, away_rating=1500)
    assert (
        p.probabilities[MarketKey.HANDICAP_HOME_MINUS_25]
        <= p.probabilities[MarketKey.HANDICAP_HOME_MINUS_15]
    )


def test_team_total_under_05_sensible():
    # очень слабая атака
    p = build_predictions(
        home_rating=1500, away_rating=1500,
        home_xg_api=0.2, away_xg_api=0.2,
    )
    assert p.probabilities[MarketKey.HOME_UNDER_05] > 0.5
