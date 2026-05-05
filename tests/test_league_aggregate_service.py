"""Юнит-тесты LeagueAggregateService.

Проверяем чистую логику расчёта агрегатов (без БД через мок-сессию)
и поведение дефолта при пустой выборке.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.league_aggregate_service import (
    DEFAULT_AVG_TOTAL,
    LeagueAggregateService,
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


@pytest.mark.asyncio
async def test_get_handles_naive_datetime_in_db_row() -> None:
    """SQLite иногда возвращает naive datetime — read-from-db не должен падать.

    Регрессия на баг: «can't subtract offset-naive and offset-aware
    datetimes» при чтении row.updated_at из SQLite.
    """
    row = MagicMock()
    row.league_id = 1
    row.n_matches = 50
    row.avg_total_goals = 2.7
    row.avg_home_goals = 1.4
    row.avg_away_goals = 1.3
    row.btts_rate = 0.5
    row.home_win_rate = 0.45
    row.draw_rate = 0.25
    row.over_25_rate = 0.52
    # Naive datetime — какой возвращает SQLite по умолчанию
    row.updated_at = datetime.utcnow() - timedelta(hours=1)

    session = MagicMock()
    session.scalar = AsyncMock(return_value=row)
    session.close = AsyncMock()

    factory = MagicMock(return_value=session)

    svc = LeagueAggregateService(factory)
    stats = await svc.get(1)

    # Не упало → fix работает; данные взяты из row
    assert stats.n_matches == 50
    assert abs(stats.avg_total - 2.7) < 1e-9
    assert stats.is_default is False


@pytest.mark.asyncio
async def test_get_uses_in_memory_cache_with_aware_datetime() -> None:
    """Повторный вызов get() в TTL — должен брать из памяти без БД."""
    svc = LeagueAggregateService(MagicMock())
    custom = LeagueStats(
        league_id=42,
        n_matches=100,
        avg_total=3.1,
        avg_home=1.7,
        avg_away=1.4,
        btts_rate=0.6,
        home_win_rate=0.5,
        draw_rate=0.2,
        over_25_rate=0.7,
    )
    svc._cache[42] = (custom, datetime.now(tz=UTC))

    result = await svc.get(42)
    assert result is custom  # тот же объект из кэша
