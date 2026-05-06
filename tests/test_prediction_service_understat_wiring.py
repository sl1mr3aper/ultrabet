"""P0-9: интеграционный тест wiring UnderstatXgProvider → PredictionService.

Проверяет, что при наличии xG-сэмплов в team_xg_samples PredictionService
использует Understat xG, а не fallback'ится на tanh-аппроксимацию.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.value_calculator import ValueCalculator
from db.models import Base, TeamXgSample
from services.prediction_service import PredictionService
from services.understat_xg_provider import UnderstatXgProvider


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_xg_samples(factory: Any, *, team: str, n: int, base_for: float, base_against: float) -> None:
    """Засеять n завершённых матчей в team_xg_samples."""
    async with factory() as s:
        for i in range(n):
            s.add(
                TeamXgSample(
                    source="understat",
                    league_slug="EPL",
                    season="2425",
                    match_id=10_000 + i,
                    match_datetime=datetime.now(tz=UTC) - timedelta(days=n - i),
                    team_name=team,
                    is_home=(i % 2 == 0),
                    xg_for=base_for,
                    xg_against=base_against,
                    goals_for=int(base_for),
                    goals_against=int(base_against),
                ),
            )
        await s.commit()


def _make_sstats_bundle(home_name: str, away_name: str) -> dict[str, Any]:
    """Минимальный bundle, достаточный для PredictionService.predict()."""
    return {
        "game": {
            "game": {
                "homeTeam": {"id": 1, "name": home_name},
                "awayTeam": {"id": 2, "name": away_name},
                "season": {
                    "league": {
                        "id": 100,
                        "name": "Premier League",
                        "country": {"name": "England"},
                    },
                },
                "date": "2026-05-10",
            },
        },
        "glicko": {
            "glicko": {
                "homeRating": 1700.0,
                "awayRating": 1500.0,
                "homeRd": 60.0,
                "awayRd": 60.0,
                # SStats не дал xG — без Understat провайдера сработает tanh
                "homeXg": None,
                "awayXg": None,
            },
        },
        "odds": [],
        "live_odds": None,
        "injuries": [],
        "last_games": None,
        "season_table": None,
        "summary": None,
        "profits": None,
    }


@pytest.mark.asyncio
async def test_prediction_service_uses_understat_xg_when_samples_exist(
    session_factory: Any,
) -> None:
    home, away = "Arsenal", "Brighton"
    # 5 матчей у каждой команды, понятный baseline xG
    await _seed_xg_samples(session_factory, team=home, n=5, base_for=2.4, base_against=0.9)
    await _seed_xg_samples(session_factory, team=away, n=5, base_for=1.0, base_against=1.7)

    provider = UnderstatXgProvider(session_factory=session_factory, last_n=10)

    # Замоканный SStatsClient: get_full_match_data возвращает наш bundle
    sstats_client = AsyncMock()
    sstats_client.get_full_match_data = AsyncMock(
        return_value=_make_sstats_bundle(home, away),
    )
    sstats_client.session = None  # external_odds выключим

    svc = PredictionService(
        sstats_client,
        value_calculator=ValueCalculator(),
        understat_xg_provider=provider,
        external_odds_enabled=False,
    )
    result = await svc.predict(12345)

    assert result is not None
    assert result.home_name == home
    assert result.away_name == away
    # Главное: provider сработал → флаг проброшен в extra
    assert result.extra.get("understat_xg_used") is True
    # Sanity-check: home_xg должно быть существенно больше away_xg
    # (Arsenal сильнее Brighton по xG-данным).
    assert result.home_xg > result.away_xg, (
        f"home_xg={result.home_xg}, away_xg={result.away_xg}"
    )


@pytest.mark.asyncio
async def test_prediction_service_fallback_when_no_understat_data(
    session_factory: Any,
) -> None:
    home, away = "Tottenham", "Crystal Palace"
    # У команд НЕТ записей в team_xg_samples — провайдер вернёт None,
    # PredictionService должен корректно отработать на старой логике.
    provider = UnderstatXgProvider(session_factory=session_factory, last_n=10)

    sstats_client = AsyncMock()
    sstats_client.get_full_match_data = AsyncMock(
        return_value=_make_sstats_bundle(home, away),
    )
    sstats_client.session = None

    svc = PredictionService(
        sstats_client,
        value_calculator=ValueCalculator(),
        understat_xg_provider=provider,
        external_odds_enabled=False,
    )
    result = await svc.predict(12345)

    assert result is not None
    # Флаг НЕ проброшен — Understat данных не нашлось.
    assert "understat_xg_used" not in result.extra


@pytest.mark.asyncio
async def test_prediction_service_works_without_understat_provider(
    session_factory: Any,
) -> None:
    """PredictionService должен работать и БЕЗ провайдера (обратная совместимость)."""
    sstats_client = AsyncMock()
    sstats_client.get_full_match_data = AsyncMock(
        return_value=_make_sstats_bundle("A", "B"),
    )
    sstats_client.session = None

    svc = PredictionService(
        sstats_client,
        value_calculator=ValueCalculator(),
        # understat_xg_provider не передан
        external_odds_enabled=False,
    )
    result = await svc.predict(12345)

    assert result is not None
    assert "understat_xg_used" not in result.extra
