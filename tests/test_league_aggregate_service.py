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


def test_fallback_uses_country_cache_when_league_unknown() -> None:
    """Если у league_id нет данных — берём агрегат по стране."""
    svc = LeagueAggregateService(MagicMock())
    # Заполняем country_cache как будто recompute_all завершился.
    svc._country_cache["spain"] = LeagueStats(
        league_id=None,
        n_matches=200,
        avg_total=2.55,
        avg_home=1.35,
        avg_away=1.20,
        btts_rate=0.49,
        home_win_rate=0.46,
        draw_rate=0.26,
        over_25_rate=0.50,
    )
    fallback = svc._fallback_stats(country="Spain", league_id=999)
    assert fallback.n_matches == 200
    assert abs(fallback.avg_total - 2.55) < 1e-9
    # league_id=999 пробрасывается — для отчёта по конкретной лиге.
    assert fallback.league_id == 999
    assert fallback.is_default is True  # это всё-таки fallback


def test_fallback_uses_global_when_country_missing() -> None:
    """Если ни лиги, ни страны нет — глобальное среднее."""
    svc = LeagueAggregateService(MagicMock())
    svc._global_stats = LeagueStats(
        league_id=None,
        n_matches=5000,
        avg_total=2.7,
        avg_home=1.45,
        avg_away=1.25,
        btts_rate=0.51,
        home_win_rate=0.45,
        draw_rate=0.25,
        over_25_rate=0.52,
    )
    fallback = svc._fallback_stats(country="Mongolia", league_id=12345)
    assert fallback.n_matches == 5000
    assert abs(fallback.avg_total - 2.7) < 1e-9
    assert fallback.league_id == 12345
    assert fallback.is_default is True


def test_fallback_returns_default_when_nothing_known() -> None:
    """Без country_cache и global_stats — DEFAULT_AVG_TOTAL."""
    svc = LeagueAggregateService(MagicMock())
    fallback = svc._fallback_stats(country="Atlantis", league_id=None)
    assert fallback.is_default is True
    assert fallback.avg_total == DEFAULT_AVG_TOTAL


def test_merge_aggregates_weighted_average() -> None:
    """Merge нескольких лиг: взвешенное по n_matches."""
    rows = [
        MagicMock(
            n_matches=100, avg_total_goals=3.0, avg_home_goals=1.6,
            avg_away_goals=1.4, btts_rate=0.55, home_win_rate=0.45,
            draw_rate=0.25, over_25_rate=0.55,
        ),
        MagicMock(
            n_matches=50, avg_total_goals=2.4, avg_home_goals=1.3,
            avg_away_goals=1.1, btts_rate=0.45, home_win_rate=0.40,
            draw_rate=0.30, over_25_rate=0.45,
        ),
    ]
    merged = LeagueAggregateService._merge_aggregates(rows)
    assert merged is not None
    assert merged.n_matches == 150
    # weighted: (3.0*100 + 2.4*50) / 150 = (300+120)/150 = 2.8
    assert abs(merged.avg_total - 2.8) < 1e-6


def test_calibrate_home_advantage_from_winrate() -> None:
    """Проверка калибровки per-league Glicko home_advantage."""
    from core.glicko_model import (
        HOME_ADVANTAGE_DEFAULT,
        calibrate_home_advantage_from_winrate,
    )

    # 35% home win → low HA
    ha_low = calibrate_home_advantage_from_winrate(0.35)
    assert 10.0 <= ha_low <= 200.0

    # 45% home win → выше чем 35%
    ha_mid = calibrate_home_advantage_from_winrate(0.45)
    assert ha_mid > ha_low

    # 55% home win — большое HA, ≤ 200 (clamp)
    ha_high = calibrate_home_advantage_from_winrate(0.55)
    assert ha_high >= ha_mid
    assert ha_high <= 200.0

    # Невалидные значения → дефолт
    assert calibrate_home_advantage_from_winrate(0.05) == HOME_ADVANTAGE_DEFAULT
    assert calibrate_home_advantage_from_winrate(0.95) == HOME_ADVANTAGE_DEFAULT
