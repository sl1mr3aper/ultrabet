"""Тесты services/clv_tracker — без реального Betfair, без реальной БД."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, PinnacleClosingOdds, PredictionOutcome
from services.clv_tracker import (
    BetfairMarketRef,
    ClvTracker,
    StaticBetfairMarketResolver,
    compute_clv,
)

# ─── compute_clv ────────────────────────────────────────────────────────────


def test_compute_clv_positive() -> None:
    # P(event)=0.55, close=2.0 → 0.55 * 2.0 - 1 = 0.10 (10% edge)
    assert compute_clv(predicted_prob=0.55, closing_odds=2.0) == pytest.approx(0.10)


def test_compute_clv_negative() -> None:
    # P=0.40, close=2.0 → -0.20 (-20%)
    assert compute_clv(predicted_prob=0.40, closing_odds=2.0) == pytest.approx(-0.20)


def test_compute_clv_none_when_missing() -> None:
    assert compute_clv(predicted_prob=None, closing_odds=2.0) is None
    assert compute_clv(predicted_prob=0.5, closing_odds=None) is None


def test_compute_clv_invalid_inputs() -> None:
    assert compute_clv(predicted_prob=0.5, closing_odds=1.0) is None  # close ≤ 1
    assert compute_clv(predicted_prob=0.5, closing_odds=0.5) is None
    assert compute_clv(predicted_prob=0.0, closing_odds=2.0) is None
    assert compute_clv(predicted_prob=1.5, closing_odds=2.0) is None


# ─── StaticBetfairMarketResolver ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_static_resolver_returns_none_for_unknown() -> None:
    r = StaticBetfairMarketResolver()
    assert await r.resolve(game_id=1, market_key="match_winner_1") is None


@pytest.mark.asyncio
async def test_static_resolver_returns_added_ref() -> None:
    r = StaticBetfairMarketResolver()
    ref = BetfairMarketRef(
        market_id="1.234", selection_id=11, market_type="MATCH_ODDS"
    )
    r.add(game_id=42, market_key="match_winner_1", ref=ref)
    out = await r.resolve(game_id=42, market_key="match_winner_1")
    assert out is ref


# ─── End-to-end: tracker + in-memory SQLite ─────────────────────────────────


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def acquire() -> Any:
        async with factory() as s:
            yield s

    yield acquire
    await engine.dispose()


class _FakeBetfair:
    """Заглушка BetfairClient: возвращает заранее заданный list_market_book."""

    def __init__(self, books: list[dict[str, Any]]) -> None:
        self.books = books
        self.calls: list[list[str]] = []

    async def list_market_book(
        self,
        market_ids: list[str],
        *,
        price_projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(market_ids)
        return self.books


@pytest.mark.asyncio
async def test_tracker_captures_close_and_computes_clv(session_factory: Any) -> None:
    # Готовим pick в БД.
    async with session_factory() as session:
        outcome = PredictionOutcome(
            game_id=100,
            market_key="match_winner_1",
            predicted_probability=0.50,
        )
        session.add(outcome)
        await session.commit()
        await session.refresh(outcome)

    resolver = StaticBetfairMarketResolver()
    resolver.add(
        game_id=100,
        market_key="match_winner_1",
        ref=BetfairMarketRef(
            market_id="1.555", selection_id=999, market_type="MATCH_ODDS"
        ),
    )
    fake_bf = _FakeBetfair(
        books=[
            {
                "marketId": "1.555",
                "runners": [
                    {
                        "selectionId": 999,
                        "lastPriceTraded": 2.20,
                        "ex": {"availableToBack": [{"price": 2.18}]},
                    }
                ],
            }
        ]
    )
    tracker = ClvTracker(
        session_factory=session_factory,
        betfair=fake_bf,  # type: ignore[arg-type]
        resolver=resolver,
    )

    captured = await tracker.capture_for_pick(outcome)
    assert captured is not None
    assert captured.closing_odds == pytest.approx(2.20)
    # CLV = 0.50 * 2.20 - 1 = 0.10
    assert captured.clv == pytest.approx(0.10)

    # Verify записано в БД (snapshot + обновлен PredictionOutcome).
    async with session_factory() as session:
        from sqlalchemy import select

        snaps = (
            await session.execute(select(PinnacleClosingOdds))
        ).scalars().all()
        assert len(snaps) == 1
        assert snaps[0].closing_odds == pytest.approx(2.20)

        latest_pick = (
            await session.execute(
                select(PredictionOutcome).order_by(
                    PredictionOutcome.id.desc()
                )
            )
        ).scalar_one()
        assert latest_pick.closing_odds == pytest.approx(2.20)
        assert latest_pick.clv == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_tracker_skips_when_no_mapping(session_factory: Any) -> None:
    async with session_factory() as session:
        outcome = PredictionOutcome(
            game_id=200,
            market_key="totals_over_25",
            predicted_probability=0.6,
        )
        session.add(outcome)
        await session.commit()
        await session.refresh(outcome)

    fake_bf = _FakeBetfair(books=[])
    tracker = ClvTracker(
        session_factory=session_factory,
        betfair=fake_bf,  # type: ignore[arg-type]
        resolver=StaticBetfairMarketResolver(),
    )
    captured = await tracker.capture_for_pick(outcome)
    assert captured is None
    assert fake_bf.calls == []  # не дошли даже до Betfair


@pytest.mark.asyncio
async def test_tracker_falls_back_to_best_back(session_factory: Any) -> None:
    """Если lastPriceTraded отсутствует — берём первый availableToBack."""
    async with session_factory() as session:
        outcome = PredictionOutcome(
            game_id=300,
            market_key="m",
            predicted_probability=0.4,
        )
        session.add(outcome)
        await session.commit()
        await session.refresh(outcome)

    resolver = StaticBetfairMarketResolver()
    resolver.add(
        game_id=300,
        market_key="m",
        ref=BetfairMarketRef(
            market_id="1.999", selection_id=10, market_type="MATCH_ODDS"
        ),
    )
    fake_bf = _FakeBetfair(
        books=[
            {
                "marketId": "1.999",
                "runners": [
                    {
                        "selectionId": 10,
                        "ex": {"availableToBack": [{"price": 3.10}]},
                    }
                ],
            }
        ]
    )
    tracker = ClvTracker(
        session_factory=session_factory,
        betfair=fake_bf,  # type: ignore[arg-type]
        resolver=resolver,
    )
    captured = await tracker.capture_for_pick(outcome)
    assert captured is not None
    assert captured.closing_odds == pytest.approx(3.10)


@pytest.mark.asyncio
async def test_aggregate_clv(session_factory: Any) -> None:
    now = datetime.now(tz=UTC)
    async with session_factory() as session:
        for i, (clv, days_ago) in enumerate([(0.10, 1), (0.05, 5), (-0.02, 10)]):
            session.add(
                PredictionOutcome(
                    game_id=1000 + i,
                    market_key="m",
                    predicted_probability=0.5,
                    closing_odds=2.0,
                    clv=clv,
                    created_at=now - timedelta(days=days_ago),
                )
            )
        await session.commit()

    tracker = ClvTracker(
        session_factory=session_factory,
        betfair=None,  # type: ignore[arg-type]
        resolver=StaticBetfairMarketResolver(),
    )
    out = await tracker.aggregate_clv(period_days=30)
    assert out["n_picks"] == 3
    assert out["avg_clv"] == pytest.approx((0.10 + 0.05 - 0.02) / 3)
    assert out["positive_clv_rate"] == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_capture_pending_closes_concurrent(session_factory: Any) -> None:
    """Сразу несколько пиков обрабатываются параллельно."""
    async with session_factory() as session:
        outcomes = []
        for i in range(3):
            o = PredictionOutcome(
                game_id=2000 + i,
                market_key=f"market_{i}",
                predicted_probability=0.5,
            )
            session.add(o)
            outcomes.append(o)
        await session.commit()
        for o in outcomes:
            await session.refresh(o)

    resolver = StaticBetfairMarketResolver()
    for i, o in enumerate(outcomes):
        resolver.add(
            game_id=o.game_id,
            market_key=o.market_key,
            ref=BetfairMarketRef(
                market_id=f"1.{i}", selection_id=i, market_type="X"
            ),
        )

    class _MultiBetfair:
        async def list_market_book(
            self,
            market_ids: list[str],
            *,
            price_projection: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            mid = market_ids[0]
            sel = int(mid.split(".")[1])
            return [
                {
                    "marketId": mid,
                    "runners": [
                        {"selectionId": sel, "lastPriceTraded": 2.0 + sel * 0.1}
                    ],
                }
            ]

    tracker = ClvTracker(
        session_factory=session_factory,
        betfair=_MultiBetfair(),  # type: ignore[arg-type]
        resolver=resolver,
    )
    captured = await tracker.capture_pending_closes(outcomes=outcomes)
    assert len(captured) == 3
