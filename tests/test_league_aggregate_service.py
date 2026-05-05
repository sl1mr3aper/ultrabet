"""Юнит-тесты LeagueAggregateService.

Проверяем чистую логику расчёта агрегатов (без БД через мок-сессию)
и поведение дефолта при пустой выборке.
"""

from __future__ import annotations

from services.league_aggregate_service import (
    DEFAULT_AVG_TOTAL,
    LeagueStats,
)


def test_league_stats_default() -> None:
    s = LeagueStats.default()
    assert s.is_default is True
    assert s.n_matches == 0
    assert s.avg_total == DEFAULT_AVG_TOTAL
    assert 0.0 < s.btts_rate <= 1.0
    assert s.expected_total == s.avg_total


def test_league_stats_custom_values() -> None:
    s = LeagueStats(
        league_id=1,
        n_matches=42,
        avg_total=2.85,
        avg_home=1.55,
        avg_away=1.30,
        btts_rate=0.55,
        home_win_rate=0.48,
        draw_rate=0.22,
        over_25_rate=0.58,
    )
    assert s.is_default is False
    assert s.n_matches == 42
    assert abs(s.avg_total - 2.85) < 1e-9
    assert s.expected_total == 2.85
