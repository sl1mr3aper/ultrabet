"""Тесты services.backtest_service — Brier/ROI/CLV агрегаты."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, PredictionOutcome
from services.backtest_service import BacktestMetrics, BacktestService


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(
    factory: Any,
    rows: list[dict[str, Any]],
) -> None:
    async with factory() as s:
        for r in rows:
            s.add(PredictionOutcome(**r))
        await s.commit()


@pytest.mark.asyncio
async def test_backtest_empty_returns_zero_metrics(session_factory: Any) -> None:
    svc = BacktestService(session_factory=session_factory)
    m = await svc.run()
    assert m.is_empty
    assert m.n_picks == 0
    assert m.brier_score is None
    assert m.roi_pct is None


@pytest.mark.asyncio
async def test_backtest_brier_and_hit_rate(session_factory: Any) -> None:
    # 4 пика: 2 сыграли (prob 0.7), 2 не сыграли (prob 0.4)
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "predicted_probability": 0.7, "hit": True},
            {"game_id": 2, "market_key": "1", "predicted_probability": 0.7, "hit": True},
            {"game_id": 3, "market_key": "1", "predicted_probability": 0.4, "hit": False},
            {"game_id": 4, "market_key": "1", "predicted_probability": 0.4, "hit": False},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    m = await svc.run()

    assert m.n_picks == 4
    assert m.n_settled == 4
    assert m.hit_rate == 0.5
    # Brier = mean(0.09, 0.09, 0.16, 0.16) = 0.125
    assert m.brier_score is not None
    assert abs(m.brier_score - 0.125) < 1e-6


@pytest.mark.asyncio
async def test_backtest_roi_with_ev_filter(session_factory: Any) -> None:
    # prob=0.6, odds=2.0 → prob*odds=1.2 (EV+); сыграл → +1.0
    # prob=0.6, odds=2.0 → не сыграл → −1.0
    # prob=0.5, odds=1.5 → prob*odds=0.75 (EV-); НЕ должен попасть в ROI
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "predicted_probability": 0.6, "actual_odds": 2.0, "hit": True},
            {"game_id": 2, "market_key": "1", "predicted_probability": 0.6, "actual_odds": 2.0, "hit": False},
            {"game_id": 3, "market_key": "1", "predicted_probability": 0.5, "actual_odds": 1.5, "hit": True},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    m = await svc.run(only_ev_plus=True)

    # 2 EV+ пика: ROI = (1.0 + (-1.0)) / 2 * 100 = 0
    assert m.roi_pct is not None
    assert abs(m.roi_pct - 0.0) < 1e-6


@pytest.mark.asyncio
async def test_backtest_roi_without_ev_filter(session_factory: Any) -> None:
    # Те же пики, но без EV-фильтра — учитывается и EV-
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "predicted_probability": 0.6, "actual_odds": 2.0, "hit": True},
            {"game_id": 2, "market_key": "1", "predicted_probability": 0.6, "actual_odds": 2.0, "hit": False},
            {"game_id": 3, "market_key": "1", "predicted_probability": 0.5, "actual_odds": 1.5, "hit": True},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    m = await svc.run(only_ev_plus=False)

    # 3 пика: profit_sum = 1.0 - 1.0 + 0.5 = 0.5; ROI = 0.5/3*100 ≈ 16.67%
    assert m.roi_pct is not None
    assert abs(m.roi_pct - (0.5 / 3 * 100)) < 1e-6


@pytest.mark.asyncio
async def test_backtest_clv_aggregation(session_factory: Any) -> None:
    # CLV = prob × close − 1
    # pred 0.5, close 2.5 → 0.25 (>0)
    # pred 0.4, close 2.0 → -0.2 (<0)
    # pred 0.3, close 4.0 → 0.2 (>0)
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "predicted_probability": 0.5, "closing_odds": 2.5, "hit": True},
            {"game_id": 2, "market_key": "1", "predicted_probability": 0.4, "closing_odds": 2.0, "hit": False},
            {"game_id": 3, "market_key": "1", "predicted_probability": 0.3, "closing_odds": 4.0, "hit": True},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    m = await svc.run()

    assert m.n_with_close == 3
    assert m.avg_clv is not None
    # avg_clv = (0.25 + (-0.2) + 0.2) / 3 = 0.0833...
    assert abs(m.avg_clv - 0.25 / 3) < 1e-6
    # 2 of 3 имеют CLV > 0
    assert m.positive_clv_rate is not None
    assert abs(m.positive_clv_rate - 2 / 3) < 1e-6


@pytest.mark.asyncio
async def test_backtest_filter_by_league_and_market(session_factory: Any) -> None:
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "league_id": 100, "market_category": "1x2", "predicted_probability": 0.6, "hit": True},
            {"game_id": 2, "market_key": "1", "league_id": 100, "market_category": "1x2", "predicted_probability": 0.6, "hit": False},
            {"game_id": 3, "market_key": "tover_2.5", "league_id": 200, "market_category": "totals", "predicted_probability": 0.5, "hit": True},
        ],
    )
    svc = BacktestService(session_factory=session_factory)

    # Только лига 100
    m100 = await svc.run(league_id=100)
    assert m100.n_picks == 2

    # Только totals
    m_tot = await svc.run(market_category="totals")
    assert m_tot.n_picks == 1

    # Лига 100 + 1x2 → 2 пика
    m100_1x2 = await svc.run(league_id=100, market_category="1x2")
    assert m100_1x2.n_picks == 2


@pytest.mark.asyncio
async def test_backtest_by_league_groups_correctly(session_factory: Any) -> None:
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "league_id": 100, "predicted_probability": 0.6, "hit": True},
            {"game_id": 2, "market_key": "1", "league_id": 100, "predicted_probability": 0.6, "hit": False},
            {"game_id": 3, "market_key": "1", "league_id": 200, "predicted_probability": 0.5, "hit": True},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    grouped = await svc.by_league()

    assert set(grouped.keys()) == {100, 200}
    assert grouped[100].n_picks == 2
    assert grouped[200].n_picks == 1
    assert grouped[100].hit_rate == 0.5
    assert grouped[200].hit_rate == 1.0


@pytest.mark.asyncio
async def test_backtest_by_market_groups_correctly(session_factory: Any) -> None:
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "market_category": "1x2", "predicted_probability": 0.6, "hit": True},
            {"game_id": 2, "market_key": "tover_2.5", "market_category": "totals", "predicted_probability": 0.5, "hit": True},
            {"game_id": 3, "market_key": "tunder_2.5", "market_category": "totals", "predicted_probability": 0.5, "hit": False},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    grouped = await svc.by_market()

    assert set(grouped.keys()) == {"1x2", "totals"}
    assert grouped["1x2"].n_picks == 1
    assert grouped["totals"].n_picks == 2


@pytest.mark.asyncio
async def test_backtest_filter_by_period(session_factory: Any) -> None:
    base_dt = datetime.now(tz=UTC)
    await _seed(
        session_factory,
        [
            {"game_id": 1, "market_key": "1", "predicted_probability": 0.6, "hit": True, "created_at": base_dt - timedelta(days=10)},
            {"game_id": 2, "market_key": "1", "predicted_probability": 0.5, "hit": False, "created_at": base_dt - timedelta(days=2)},
            {"game_id": 3, "market_key": "1", "predicted_probability": 0.5, "hit": True, "created_at": base_dt - timedelta(days=1)},
        ],
    )
    svc = BacktestService(session_factory=session_factory)
    # Только последние 5 дней
    m = await svc.run(period_from=base_dt - timedelta(days=5))
    assert m.n_picks == 2


@pytest.mark.asyncio
async def test_backtest_metrics_dataclass_emptiness() -> None:
    m = BacktestMetrics(
        n_picks=0, n_settled=0, n_with_odds=0, n_with_close=0,
        brier_score=None, roi_pct=None, avg_clv=None,
        positive_clv_rate=None, hit_rate=None,
    )
    assert m.is_empty
