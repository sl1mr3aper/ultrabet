"""Тесты value_filter."""

from __future__ import annotations

import pytest

from services.value_filter import (
    ValueBet,
    apply_filters,
    exclude_leagues,
    exclude_markets,
    min_probability,
    min_value_percent,
    odds_range,
    only_leagues,
    only_markets,
    pipeline,
    sort_by_odds_asc,
    sort_by_probability_desc,
    sort_by_value_desc,
    to_dict_list,
    top_n,
)


def _bet(**kwargs):
    defaults = {
        "game_id": 1, "game_label": "A vs B", "market": "home",
        "bookmaker": "bet365", "probability": 0.55, "odds": 2.0,
        "fair_odds": 1 / 0.55, "value_percent": 10.0, "league": "EPL",
    }
    defaults.update(kwargs)
    return ValueBet(**defaults)


@pytest.fixture
def bets():
    return [
        _bet(market="home", odds=1.8, probability=0.6, value_percent=8, league="EPL"),
        _bet(market="away", odds=2.5, probability=0.4, value_percent=15, league="LaLiga"),
        _bet(market="draw", odds=3.5, probability=0.3, value_percent=20, league="SerieA"),
        _bet(market="over_2_5", odds=1.9, probability=0.55, value_percent=5, league="EPL"),
    ]


def test_min_probability(bets):
    filtered = apply_filters(bets, [min_probability(0.5)])
    assert len(filtered) == 2


def test_min_value_percent(bets):
    filtered = apply_filters(bets, [min_value_percent(10.0)])
    assert len(filtered) == 2


def test_odds_range(bets):
    filtered = apply_filters(bets, [odds_range(2.0, 3.0)])
    assert len(filtered) == 1
    assert filtered[0].market == "away"


def test_only_markets(bets):
    filtered = apply_filters(bets, [only_markets("home", "away")])
    assert len(filtered) == 2


def test_exclude_markets(bets):
    filtered = apply_filters(bets, [exclude_markets("over_2_5")])
    assert len(filtered) == 3


def test_only_leagues(bets):
    filtered = apply_filters(bets, [only_leagues("EPL")])
    assert len(filtered) == 2


def test_exclude_leagues(bets):
    filtered = apply_filters(bets, [exclude_leagues("EPL")])
    assert len(filtered) == 2


def test_combined_filters(bets):
    filtered = apply_filters(
        bets,
        [min_probability(0.4), min_value_percent(10), odds_range(1.0, 3.0)],
    )
    assert len(filtered) == 1
    assert filtered[0].market == "away"


def test_sort_by_value_desc(bets):
    sorted_b = sort_by_value_desc(bets)
    assert sorted_b[0].value_percent == 20
    assert sorted_b[-1].value_percent == 5


def test_sort_by_odds_asc(bets):
    sorted_b = sort_by_odds_asc(bets)
    assert sorted_b[0].odds == 1.8
    assert sorted_b[-1].odds == 3.5


def test_sort_by_probability_desc(bets):
    sorted_b = sort_by_probability_desc(bets)
    assert sorted_b[0].probability == 0.6
    assert sorted_b[-1].probability == 0.3


def test_top_n(bets):
    assert len(top_n(bets, 2)) == 2


def test_pipeline(bets):
    result = pipeline(
        bets,
        filters=[min_value_percent(10)],
        sort_fn=sort_by_value_desc,
        limit=1,
    )
    assert len(result) == 1
    assert result[0].value_percent == 20


def test_to_dict_list(bets):
    out = to_dict_list(bets)
    assert len(out) == 4
    assert "value_percent" in out[0]
