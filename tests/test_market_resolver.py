"""Тесты резолвера рынков."""

from __future__ import annotations

import pytest

from services.market_resolver import resolve_market


@pytest.mark.parametrize(
    "key,home,away,expected",
    [
        ("home", 2, 1, True),
        ("home", 1, 2, False),
        ("home_win", 3, 0, True),
        ("away", 0, 2, True),
        ("away_win", 1, 1, False),
        ("draw", 1, 1, True),
        ("draw", 2, 1, False),
        # тоталы
        ("over_2.5", 2, 1, True),
        ("under_2.5", 1, 1, True),
        ("over_1.5", 1, 0, False),
        ("under_3.5", 5, 0, False),
        # BTTS
        ("btts_yes", 1, 2, True),
        ("btts_yes", 3, 0, False),
        ("btts_no", 3, 0, True),
        ("btts_no", 1, 1, False),
        # сухие победы
        ("home_win_clean", 3, 0, True),
        ("home_win_clean", 3, 1, False),
        ("away_win_clean", 0, 2, True),
        # двойной шанс
        ("double_chance_1x", 1, 1, True),
        ("double_chance_1x", 0, 2, False),
        ("double_chance_12", 2, 1, True),
        ("double_chance_12", 1, 1, False),
        # гандикап
        ("handicap_home_-1", 2, 0, True),
        ("handicap_home_-1", 1, 0, False),
        ("handicap_away_1", 0, 0, True),
        # командные тоталы
        ("home_over_0.5", 1, 0, True),
        ("home_over_1.5", 1, 0, False),
        ("away_under_0.5", 1, 0, True),
    ],
)
def test_resolve_known_market(key, home, away, expected):
    assert resolve_market(key, home, away) is expected


def test_unknown_market_returns_none():
    assert resolve_market("weird_market", 1, 0) is None
